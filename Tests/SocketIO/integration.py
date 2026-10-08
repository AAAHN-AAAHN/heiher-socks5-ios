#!/usr/bin/env python3
"""Independent socket-boundary expectations; no packet capture or meter callbacks."""
import argparse,json,os,select,socket,struct,subprocess,tempfile,threading,time
from pathlib import Path

def udp_socket(family,label):
 # Match the inherited UDP fixture's capacity; keep every large-packet oracle.
 s=socket.socket(family,socket.SOCK_DGRAM)
 try:
  actual={}
  for name,option,size in [('send',socket.SO_SNDBUF,256*1024),('receive',socket.SO_RCVBUF,512*1024)]:
   try:s.setsockopt(socket.SOL_SOCKET,option,size)
   except OSError as error:
    raise RuntimeError(f'UDP fixture {label}: cannot set {name} buffer to {size}; host socket limits must allow the unchanged large-packet matrix') from error
   actual[name]=s.getsockopt(socket.SOL_SOCKET,option)
   if actual[name]<65536:
    raise RuntimeError(f'UDP fixture {label}: {name} buffer is {actual[name]} after requesting {size}; host socket limits must permit at least 65536 bytes for the unchanged 64000-byte payload matrix')
  print('UDP fixture buffers:',json.dumps(dict(peer=label,family=int(family),**actual)),flush=True)
  return s
 except BaseException:
  s.close();raise

def exact(s,n):
 b=b''
 while len(b)<n:
  x=s.recv(n-len(b))
  if not x:raise RuntimeError('short reply')
  b+=x
 return b

def addr(ip,port,domain=False):
 if domain:return b'\x03'+bytes([len(ip)])+ip.encode()+struct.pack('!H',port)
 family=socket.AF_INET6 if ':' in ip else socket.AF_INET
 return bytes([4 if family==socket.AF_INET6 else 1])+socket.inet_pton(family,ip)+struct.pack('!H',port)

def reply(s):
 h=exact(s,4);assert h[:3]==b'\x05\x00\x00',h
 n=6 if h[3]==1 else 18
 tail=exact(s,n)
 return socket.inet_ntop(socket.AF_INET if h[3]==1 else socket.AF_INET6,tail[:-2]),int.from_bytes(tail[-2:],'big'),4+n

class Host:
 def __init__(self,binary,out,workers=4,auth=False):
  self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True)
  # Reserve the same wildcard/family as the native listener, not only 127.0.0.1.
  with socket.socket(socket.AF_INET6) as s:
   s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0);s.bind(('::',0));self.port=s.getsockname()[1]
  cfg=self.out/'config.yml';cfg.write_text(f"main:\n  workers: {workers}\n  listen-address: '::'\n  port: {self.port}\n  udp-port: 0\n  bind-address-v4: ''\n  bind-address-v6: ''\n"+("auth:\n  username: user\n  password: secret\n" if auth else ''))
  self.log=(self.out/'server.log').open('w');self.p=subprocess.Popen([str(binary),str(cfg)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,bufsize=1)
  assert self.p.stdout.readline() == 'READY\n'
  self.auth=auth;self.rows={};self.totals=[0,0];self.points=[]
  for _ in range(300):
   try:
    self.control('127.0.0.1').close()
    break
   except OSError:time.sleep(.01)
  else:raise RuntimeError('not ready')
 def snapshot(self):
  self.p.stdin.write('clients\n');self.p.stdin.flush();l=self.p.stdout.readline().split();assert l[0]=='CLIENTS',l
  rows={}
  for _ in range(int(l[1])):
   v=self.p.stdout.readline().split();assert v[0]=='CLIENT';rows[v[2]]=list(map(int,v[3:]))
  self.p.stdin.write('stats\n');self.p.stdin.flush();t=self.p.stdout.readline().split();assert t[0]=='STATS'
  return rows,list(map(int,t[1:]))
 def add(self,ip,inp=0,out=0):
  r=self.rows.setdefault(ip,[0,0]);r[0]+=inp;r[1]+=out;self.totals[0]+=inp;self.totals[1]+=out
 def check(self,label):
  deadline=time.monotonic()+2
  while True:
   rows,total=self.snapshot()
   nonzero={k:v for k,v in rows.items() if any(v)}
   want={k:v for k,v in self.rows.items() if any(v)}
   if nonzero==want and total==self.totals:break
   if time.monotonic()>deadline:raise AssertionError((label,nonzero,want,total,self.totals))
   time.sleep(.002)
  self.points.append(dict(label=label,rows=nonzero,total=total));(self.out/'results.json').write_text(json.dumps(self.points,indent=2))
 def control(self,source='127.0.0.2'):
  s=socket.socket(socket.AF_INET6 if ':' in source else socket.AF_INET);s.settimeout(2);s.bind((source,0));s.connect(('::1' if ':' in source else '127.0.0.1',self.port))
  if self.auth:
   s.sendall(b'\x05\x01\x02');assert exact(s,2)==b'\x05\x02';s.sendall(b'\x01\x04user\x06secret');assert exact(s,2)==b'\x01\x00';self.add(source,4,16)
  else:s.sendall(b'\x05\x01\x00');assert exact(s,2)==b'\x05\x00';self.add(source,2,3)
  return s
 def connect(self,source,dest,port,cmd=1,domain=False):
  s=self.control(source);request=b'\x05'+bytes([cmd])+b'\x00'+addr(dest,port,domain);s.sendall(request);relay=reply(s);self.add(source,relay[2],len(request));return s,relay
 def close(self):
  if self.p.poll() is None:
   self.p.stdin.write('quit\n');self.p.stdin.flush()
   try:self.p.wait(timeout=5)
   except subprocess.TimeoutExpired:self.p.kill();self.p.wait();raise
  assert self.p.returncode==0,self.p.returncode
  self.p.stdin.close();self.p.stdout.close();self.log.close()

class Echo:
 def __init__(self,ip,udp=False):
  self.ip=ip;self.udp=udp;family=socket.AF_INET6 if ':' in ip else socket.AF_INET
  self.s=udp_socket(family,'echo '+ip) if udp else socket.socket(family,socket.SOCK_STREAM)
  self.s.bind((ip,0));self.port=self.s.getsockname()[1];self.running=True;self.error=None
  if not udp:self.s.listen()
  self.s.settimeout(.1);self.children=[];self.t=threading.Thread(target=self.loop);self.t.start()
 def loop(self):
  try:
   while self.running:
    try:
     if self.udp:
      b,p=self.s.recvfrom(65536);self.s.sendto(b[::-1]+b'END',p)
     else:
      c,_=self.s.accept();t=threading.Thread(target=self.tcp,args=(c,));self.children.append(t);t.start()
    except socket.timeout:pass
  except Exception as e:self.error=repr(e)
 def tcp(self,c):
  try:
   c.settimeout(3);h=exact(c,4);n=int.from_bytes(h,'big');b=exact(c,n);r=b[::-1]+b'END';c.sendall(r);c.shutdown(socket.SHUT_WR)
   while c.recv(256):pass
  finally:c.close()
 def close(self):
  self.running=False;self.t.join();self.s.close()
  for t in self.children:t.join()
  assert self.error is None,self.error

def suite(binary,out,workers,auth):
 h=Host(binary,out,workers,auth);servers=[]
 try:
  # A and B are both registered clients, independent of their endpoint role.
  a=h.control('127.0.0.2');b=h.control('127.0.0.3');h.check('both-client-handshakes')
  for source,dest in [('127.0.0.2','127.0.0.3'),('127.0.0.3','127.0.0.2'),('127.0.0.2','::1'),('::1','127.0.0.3'),('127.0.0.2','127.0.0.2')]:
   e=Echo(dest);servers.append(e)
   for size in [0,1,1000,64000]:
    s,_=h.connect(source,dest,e.port,domain=':' not in dest)
    data=bytes((i*31+7)&255 for i in range(size));frame=struct.pack('!I',size)+data
    s.sendall(frame);s.shutdown(socket.SHUT_WR);r=exact(s,size+3);assert r==data[::-1]+b'END';assert not s.recv(1);s.close()
    h.add(source,size+3,size+4);h.add(dest,size+4,size+3);h.check(f'tcp-{source}-{dest}-{size}')
   u=Echo(dest,True);servers.append(u)
   ctrl,relay=h.connect(source,'::' if ':' in source else '0.0.0.0',0,cmd=3)
   client=udp_socket(socket.AF_INET6 if ':' in source else socket.AF_INET,'client '+source);client.bind((source,0));client.settimeout(2)
   rip=relay[0]
   for size in [0,1,64,1499,1500,1501,2000,48001,64000]:
    data=bytes((i*17+3)&255 for i in range(size));header=b'\x00\x00\x00'+addr(dest,u.port)
    client.sendto(header+data,(rip,relay[1]));r,_=client.recvfrom(65536);head=10 if r[3]==1 else 22;assert r[head:]==data[::-1]+b'END'
    h.add(source,len(r),len(header)+size);h.add(dest,size,size+3);h.check(f'udp-{source}-{dest}-{size}')
   # Malformed client bytes were consumed by OS/application even though no forwarding.
   bad=b'\x01\x00\x00'+addr(dest,u.port)+b'bad';client.sendto(bad,(rip,relay[1]));h.add(source,0,len(bad));h.check(f'udp-rejected-{source}-{dest}')
   client.close();ctrl.close()
  # FWD UDP-over-TCP counts entire submitted framing (including incomplete input).
  dest='127.0.0.3';u=Echo(dest,True);servers.append(u)
  s,_=h.connect('127.0.0.2','0.0.0.0',0,cmd=5)
  for size in [0,64,2001]:
   data=bytes([17])*size;address=addr(dest,u.port);frame=struct.pack('!HB',size,3+len(address))+address+data;s.sendall(frame)
   head=exact(s,3);n,hl=struct.unpack('!HB',head);tail=exact(s,hl-3+n);assert tail[hl-3:]==data[::-1]+b'END'
   h.add('127.0.0.2',hl+n,len(frame));h.add(dest,size,size+3);h.check(f'udp-over-tcp-{size}')
  incomplete=b'\x00\x0a\x0a\x01\x7f';s.sendall(incomplete);s.shutdown(socket.SHUT_WR);h.add('127.0.0.2',0,len(incomplete));h.check('incomplete-frame-consumed');s.close()
  # Bad negotiation consumes only bytes actually read, not all bytes offered by client.
  c=socket.socket();c.bind(('127.0.0.4',0));c.settimeout(1);c.connect(('127.0.0.1',h.port));c.sendall(b'\x04\x01'+b'extra-not-read');assert exact(c,2)==b'\x05\xff';c.close();h.add('127.0.0.4',2,2);h.check('bad-version-consumed-prefix')
  a.close();b.close();h.check('session-close-retains')
  # Direct A/B traffic does NOT enter this program/socket boundary.
  e=Echo('127.0.0.3');servers.append(e);c=socket.socket();c.bind(('127.0.0.2',0));c.connect(('127.0.0.3',e.port));c.sendall(b'\0\0\0\3abc');c.shutdown(socket.SHUT_WR);assert exact(c,6)==b'cbaEND';c.close();h.check('direct-bypass-not-counted')
  return dict(workers=workers,auth=auth,checkpoints=len(h.points),rows=h.rows,totals=h.totals)
 finally:
  for e in servers:e.close()
  h.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--host',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--workers',type=int,nargs='+',default=[1,4,8]);args=p.parse_args()
 results=[]
 for w in args.workers:
  for auth in [False,True]:
   r=suite(args.host.resolve(),args.output/f'w{w}-auth{int(auth)}',w,auth);results.append(r);print('PASS',r,flush=True)
 (args.output/'summary.json').write_text(json.dumps(results,indent=2))
