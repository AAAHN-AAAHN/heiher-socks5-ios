import argparse,json,time
from pathlib import Path
from integration import Host
p=argparse.ArgumentParser();p.add_argument('--host',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
h=Host(a.host.resolve(),a.output,4,False);records=[]
def generation():
 h.p.stdin.write('generation\n');h.p.stdin.flush();line=h.p.stdout.readline().split();assert line[0]=='GENERATION';return int(line[1])
try:
 for cycle in range(3):
  c=h.control('127.0.0.2');h.check('handshake before restart '+str(cycle));c.close();time.sleep(.05)
  before=h.snapshot();old_generation=generation();assert all(before[1])
  h.p.stdin.write('restart\n');h.p.stdin.flush();line=h.p.stdout.readline().split();assert line[0]=='STATS';assert list(map(int,line[1:]))==[0,0]
  after=h.snapshot();assert after==({'Unattributed':[0,0]},[0,0]);assert generation()==old_generation+1
  h.rows={};h.totals=[0,0]
  records.append(dict(cycle=cycle,before=before,after=after,generation=old_generation+1))
  for _ in range(100):
   try:h.control('127.0.0.1').close();break
   except ConnectionRefusedError:time.sleep(.01)
  else:raise AssertionError('restart failed')
  h.check('fresh handshake after restart '+str(cycle))
 a.output.mkdir(parents=True,exist_ok=True);(a.output/'restart.json').write_text(json.dumps(records,indent=2))
finally:h.close()
print('PASS: 3 actual native Stop/Start cycles reset totals and peer rows, advance generation once, and count fresh socket traffic')
