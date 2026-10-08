#!/usr/bin/env python3
"""Test current observed helper bodies, registry and actual network integration.
Controlled syscall fixtures and real-network checks are separate evidence.
"""
import argparse,json,subprocess,sys
from pathlib import Path
from loopback import prepared_loopback
HERE=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('native',type=Path);p.add_argument('--cc',default='cc');p.add_argument('--mode',choices=['buffered','splice'],default='buffered')
p.add_argument('--output',type=Path,help='Keep executables and results outside the native source inputs')
features=json.loads((HERE.parents[1]/'Build/features.json').read_text())['features']
p.add_argument('--composition',choices=['statistics','integrated'],default='integrated' if 'server' in features else 'statistics');a=p.parse_args()
n=a.native.resolve();out=a.output.resolve() if a.output else n/'build/socket-io-tests';out.mkdir(parents=True,exist_ok=True);host=out/'meter-host'
def run(args,timeout=None):
 print('+',' '.join(map(str,args)),flush=True);subprocess.run(list(map(str,args)),check=True,timeout=timeout)
task=n/'third-part/hev-task-system'
run([sys.executable,HERE/'loopback_check.py'])
run([sys.executable,HERE/'contract.py',n,'--composition',a.composition])
run([a.cc,'-O2','-pthread','-I'+str(n/'src'),HERE/'meter_host.c',
     n/'bin/libhev-socks5-server.a',n/'third-part/yaml/bin/libyaml.a',
     task/'bin/libhev-task-system.a','-o',host])
for name,defines in [('socket_observer',[]),('socket_observer',['-DFORCE_FALLBACK']),('stream_matrix',['-DENABLE_IO_SPLICE_SYSCALL'] if a.mode=='splice' else []),('registry',[]),('worker_boundaries',[])]:
 exe=out/(name+('-fallback' if '-DFORCE_FALLBACK' in defines else ''))
 run([a.cc,'-O2','-std=gnu11','-Wall','-Werror','-Wno-unused-function',*defines,'-I'+str(n/'src/core/src'),'-I'+str(task/'src'),'-I'+str(task/'include'),HERE/(name+'.c'),task/'bin/libhev-task-system.a','-pthread','-o',exe]);run([exe])
exe=out/'snapshot-rows'
run([a.cc,'-O2','-pthread','-I'+str(n/'src'),'-I'+str(n/'src/core/src'),
     HERE/'snapshot_rows.c',n/'bin/libhev-socks5-server.a',
     n/'third-part/yaml/bin/libyaml.a',task/'bin/libhev-task-system.a','-o',exe])
run([exe])
with prepared_loopback():
 run([sys.executable,HERE/'integration.py','--host',host,'--output',out/'network'],timeout=120)
 run([sys.executable,HERE/'pair_example.py','--host',host,'--output',out/'pair'],timeout=120)
 run([sys.executable,HERE/'restart.py','--host',host,'--output',out/'restart'],timeout=120)

if sys.platform == 'linux':
 exe=out/'accept-reset'
 run([a.cc,'-O2','-pthread','-I'+str(n/'src'),'-I'+str(n/'src/misc'),
      '-I'+str(n/'src/core/include'),'-I'+str(task/'include'),HERE/'accept_reset.c',
      n/'bin/libhev-socks5-server.a',n/'third-part/yaml/bin/libyaml.a',
      task/'bin/libhev-task-system.a','-Wl,--wrap=hev_socks5_session_new','-o',exe])
 for workers in (1,4,8):
  for family in (4,6): run([exe,str(workers),str(family)])
