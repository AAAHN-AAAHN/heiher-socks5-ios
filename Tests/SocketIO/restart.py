import argparse,json,time
from pathlib import Path
from integration import Host
p=argparse.ArgumentParser();p.add_argument('--host',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
h=Host(a.host.resolve(),a.output,4,False);records=[]
try:
 for cycle in range(3):
  c=h.control('127.0.0.2');h.check('handshake before restart '+str(cycle));c.close();time.sleep(.05)
  before=h.snapshot();h.p.stdin.write('restart\n');h.p.stdin.flush();line=h.p.stdout.readline().split();assert line[0]=='STATS';assert list(map(int,line[1:]))==before[1]
  after=h.snapshot();assert before==after
  h.rows={k:v[:] for k,v in after[0].items()};h.totals=after[1][:]
  records.append(dict(cycle=cycle,before=before,after=after))
  for _ in range(100):
   try:h.control('127.0.0.1').close();break
   except ConnectionRefusedError:time.sleep(.01)
  else:raise AssertionError('restart failed')
 a.output.mkdir(parents=True,exist_ok=True);(a.output/'restart.json').write_text(json.dumps(records,indent=2))
finally:h.close()
print('PASS: 3 native Stop/Start cycles preserve all peer counters and rows')
