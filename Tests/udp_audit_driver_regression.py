#!/usr/bin/env python3
"""Rejected and failed UDP audits must not retain an earlier success marker."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import udp_compat_audit as audit


class AuditDriverTests(unittest.TestCase):
    def check_failure(self, *, existing_core=False, wrong_composition=False,
                      previous_success=True):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'artifacts'
            core = Path(directory) / 'core'
            if previous_success:
                out.mkdir()
                (out / 'SUCCESS.txt').write_text('Previous successful run\n')
                (out / 'previous.log').write_text('Preserve diagnostic evidence\n')
            if existing_core:
                core.mkdir()
            config = dict(audit.CONFIG)
            if wrong_composition:
                config['features'] = ['udp', 'statistics']
            with patch.multiple(audit, OUT=out, CORE=core, CONFIG=config), patch.object(
                    audit, 'run', side_effect=RuntimeError('source command failed')) as run:
                rejected = existing_core or wrong_composition
                with self.assertRaises(SystemExit if rejected else RuntimeError):
                    audit.main()
                self.assertEqual(run.call_count, 0 if rejected else 1)
            self.assertFalse((out / 'SUCCESS.txt').exists())
            if previous_success:
                self.assertEqual((out / 'previous.log').read_text(), 'Preserve diagnostic evidence\n')

    def test_existing_checkout_invalidates_success(self):
        self.check_failure(existing_core=True)

    def test_wrong_composition_invalidates_success(self):
        self.check_failure(wrong_composition=True)

    def test_failed_command_invalidates_success(self):
        self.check_failure()

    def test_fresh_failure_does_not_publish_success(self):
        self.check_failure(previous_success=False)

    def test_optimized_python_invalidates_success(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'SUCCESS.txt'
            marker.write_text('Previous successful run\n')
            code = ('from pathlib import Path; import udp_compat_audit as audit; '
                    'audit.OUT = Path(' + repr(directory) + '); audit.main()')
            result = subprocess.run([sys.executable, '-O', '-c', code],
                                    cwd=Path(__file__).resolve().parent,
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Assertions are required', result.stderr)
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
