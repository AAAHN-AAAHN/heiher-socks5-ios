#!/usr/bin/env python3
"""Preserve exact historical controls and validate the current loop-audio contract."""
from pathlib import Path
import platform
import runpy
import subprocess
import sys

if not __debug__:
    raise SystemExit('Assertions must be enabled.')

HERE = Path(__file__).resolve().parent
history = runpy.run_path(str(HERE / 'historical_checks.py'))['run_historical']

if platform.system() == 'Darwin':
    history('check_subscription.py')
else:
    print('Historical Combine subscriber requires Darwin; current Foundation mailbox runs below.', flush=True)
subprocess.run([sys.executable, str(HERE / 'check_loop_audio.py'), '--group', 'facade', '--case', 'notifications'], check=True)
