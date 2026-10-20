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

history('check_async_session.py')
subprocess.run([sys.executable, str(HERE / 'check_loop_audio.py'), '--group', 'adapter'], check=True)
