#!/usr/bin/env python3
"""Preserve exact historical controls and validate the current loop-audio contract."""
from pathlib import Path
import argparse
import runpy
import subprocess
import sys

if not __debug__:
    raise SystemExit('Assertions must be enabled.')

parser = argparse.ArgumentParser()
parser.add_argument('--core', type=Path, help='Prepared patched Hev source for real native Echo integration')
options = parser.parse_args()
HERE = Path(__file__).resolve().parent
history = runpy.run_path(str(HERE / 'historical_checks.py'))['run_historical']

history('run_checks.py')
subprocess.run([sys.executable, str(HERE / 'check_loop_audio.py')], check=True)

for entry in ('check_udp_echo.py', 'UDPEchoTransportTests.py', 'UDPEchoSchedulerTests.py'):
    subprocess.run([sys.executable, str(HERE / entry)], check=True)
if options.core is not None:
    subprocess.run([sys.executable, str(HERE / 'check_udp_echo_native.py'), '--native', str(options.core)], check=True)
else:
    print('Native UDP Echo integration not run: supply --core with the prepared patched source.', flush=True)
