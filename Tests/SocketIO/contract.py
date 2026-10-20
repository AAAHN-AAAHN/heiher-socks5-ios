#!/usr/bin/env python3
from pathlib import Path
import argparse,hashlib,json
ROOT=Path(__file__).resolve().parents[2]
features=json.loads((ROOT/'Build/features.json').read_text())['features']
parser=argparse.ArgumentParser(description='Check the exact common meter and composed native source.')
parser.add_argument('native',type=Path)
parser.add_argument('--composition',choices=['statistics','integrated'],
                    default='integrated' if 'server' in features else 'statistics')
args=parser.parse_args()
native=args.native.resolve()
manifest=json.loads((ROOT/'Tests/SocketIO/worker-native.json').read_text())
expected={**manifest['common'],**manifest['compositions'][args.composition]}
for path,digest in expected.items():
    assert hashlib.sha256((native/path).read_bytes()).hexdigest()==digest,path
meter=(native/'src/core/src/worker_meter.c').read_text()
assert 'pthread_mutex' not in meter and '_Thread_local' not in meter
assert '_Atomic uint64_t' not in meter and '__atomic_fetch_add_8' not in meter
assert 'counter_read' in meter and 'memory_order_acquire' in meter and 'memory_order_release' in meter
assert 'wm_worker_release' in meter and 'identity->parts' in meter
worker=(native/'src/hev-socks5-worker.c').read_text()
proxy=(native/'src/hev-socks5-proxy.c').read_text()
assert 'hev_meter_worker_enter ()' in proxy and 'hev_meter_prepare ()' in proxy
assert 'hev_meter_worker_leave ()' in proxy
assert 'accept (fd, (struct sockaddr *)&peer' in worker
assert 'static void\nsocket_observer' in (native/'src/core/src/hev-socks5-meter.c').read_text()
for p in native.rglob('*.c'):
    text=p.read_text(errors='replace')
    assert 'hev_socks5_transfer_add' not in text,str(p)
print('PASS: exact Statistics meter and composed hooks, atomic publication, no obsolete collector')
