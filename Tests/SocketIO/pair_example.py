#!/usr/bin/env python3
"""Separate A/B example: both peers hold SOCKS controls; B also hosts a service."""
import argparse,json,socket,threading
from pathlib import Path
from integration import Host,exact,addr,reply
p=argparse.ArgumentParser();p.add_argument('--host',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
listener=socket.socket();listener.bind(('127.0.0.3',0));listener.listen();port=listener.getsockname()[1];errors=[]
def service():
 try:
  s,_=listener.accept()
  with s:
   assert exact(s,1000)==b'A'*1000
   s.sendall(b'B'*200)
 except BaseException as e:errors.append(repr(e))
t=threading.Thread(target=service);t.start();h=Host(a.host.resolve(),a.output/'host',4,False)
try:
 client=h.control('127.0.0.2');other=h.control('127.0.0.3');h.check('two negotiated controls')
 request=b'\x05\x01\x00'+addr('127.0.0.3',port)
 client.sendall(request);_,_,n=reply(client);h.add('127.0.0.2',n,len(request));h.check('A connects to B service')
 before=h.snapshot()
 client.sendall(b'A'*1000);client.shutdown(socket.SHUT_WR);assert exact(client,200)==b'B'*200
 while client.recv(100):pass
 h.add('127.0.0.2',200,1000);h.add('127.0.0.3',1000,200);h.check('data in both roles')
 after=h.snapshot();delta={ip:[b-a for a,b in zip(before[0][ip],after[0][ip])] for ip in ('127.0.0.2','127.0.0.3')}
 assert delta=={'127.0.0.2':[200,1000],'127.0.0.3':[1000,200]},delta
 (a.output/'pair-example.json').write_text(json.dumps(dict(before=before,after=after,data_phase_delta=delta,scope='socket bytes; SOCKS handshake recorded separately, no OS headers'),indent=2)+'\n')
 client.close();other.close();t.join(timeout=3);assert not t.is_alive() and not errors
finally:
 listener.close();h.close()
print('PASS:',delta)
