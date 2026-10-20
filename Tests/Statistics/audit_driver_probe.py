#!/usr/bin/env python3
"""A rejected or failed audit must not retain an earlier success marker."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import audit


class AuditDriverTests(unittest.TestCase):
    def check_failure(self, *, existing_core=False, previous_success=True):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'artifacts'
            core = Path(directory) / 'core'
            if previous_success:
                out.mkdir()
                (out / 'SUCCESS.txt').write_text('Previous successful run\n')
                (out / 'previous.log').write_text('Preserve diagnostic evidence\n')
            if existing_core:
                core.mkdir()
            with patch.multiple(audit, OUT=out, CORE=core), patch.object(
                    audit, 'inspect_sources', side_effect=RuntimeError('source check failed')) as inspect:
                expected = SystemExit if existing_core else RuntimeError
                with self.assertRaises(expected):
                    audit.main()
                self.assertEqual(inspect.call_count, 0 if existing_core else 1)
            self.assertFalse((out / 'SUCCESS.txt').exists())
            if previous_success:
                self.assertEqual((out / 'previous.log').read_text(), 'Preserve diagnostic evidence\n')

    def test_existing_checkout_rejects_stale_success(self):
        self.check_failure(existing_core=True)

    def test_failed_source_check_removes_stale_success(self):
        self.check_failure()

    def test_fresh_failure_does_not_publish_success(self):
        self.check_failure(previous_success=False)


if __name__ == '__main__':
    unittest.main()
