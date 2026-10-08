#!/usr/bin/env python3
"""Exercise fixture ownership and failure cleanup without changing host addresses."""
from contextlib import redirect_stderr
import io
import subprocess
import unittest
from unittest.mock import patch

import loopback


class LoopbackTests(unittest.TestCase):
    def environment(self, initial, fail_add=None, fail_remove=None):
        addresses = set(initial)
        commands = []

        def command(args):
            commands.append(args)
            if args == ['/sbin/ifconfig', 'lo0']:
                return ''.join('    inet ' + address + ' netmask 0xffffffff\n'
                               for address in sorted(addresses))
            address = args[5]
            self.assertEqual(args[:5], ['sudo', '-n', '/sbin/ifconfig', 'lo0', 'inet'])
            if args[-1] == 'alias':
                addresses.add(address)
                if address == fail_add:
                    raise subprocess.TimeoutExpired(args, 10)
            else:
                self.assertEqual(args[-1], '-alias')
                if address == fail_remove:
                    raise subprocess.CalledProcessError(1, args)
                addresses.remove(address)
            return ''

        return addresses, commands, command

    def test_preexisting_alias_is_preserved(self):
        before = {'127.0.0.1', '127.0.0.3'}
        addresses, commands, command = self.environment(before)
        with patch.object(loopback.sys, 'platform', 'darwin'), \
                patch.object(loopback, 'command', command), \
                patch.object(loopback, 'verify_bindings') as verify:
            with loopback.prepared_loopback():
                self.assertTrue(set(loopback.PEERS) <= addresses)
            verify.assert_called_once_with()
        self.assertEqual(addresses, before)
        self.assertFalse(any('127.0.0.3' in args for args in commands))

    def test_partial_setup_timeout_restores_attempted_aliases(self):
        addresses, _, command = self.environment({'127.0.0.1'}, fail_add='127.0.0.3')
        with patch.object(loopback.sys, 'platform', 'darwin'), \
                patch.object(loopback, 'command', command), \
                patch.object(loopback, 'verify_bindings') as verify:
            with self.assertRaises(subprocess.TimeoutExpired):
                with loopback.prepared_loopback():
                    self.fail('setup failure must not enter the test body')
            verify.assert_not_called()
        self.assertEqual(addresses, {'127.0.0.1'})

    def test_body_failure_restores_all_new_aliases(self):
        addresses, _, command = self.environment({'127.0.0.1'})
        primary = ValueError('native fixture failed')
        with patch.object(loopback.sys, 'platform', 'darwin'), \
                patch.object(loopback, 'command', command), \
                patch.object(loopback, 'verify_bindings'):
            with self.assertRaises(ValueError) as caught:
                with loopback.prepared_loopback():
                    raise primary
        self.assertIs(caught.exception, primary)
        self.assertEqual(addresses, {'127.0.0.1'})

    def test_cleanup_failure_preserves_primary_and_attempts_other_removals(self):
        addresses, _, command = self.environment({'127.0.0.1'}, fail_remove='127.0.0.3')
        errors = io.StringIO()
        primary = ValueError('native fixture failed')
        with patch.object(loopback.sys, 'platform', 'darwin'), \
                patch.object(loopback, 'command', command), \
                patch.object(loopback, 'verify_bindings'), redirect_stderr(errors):
            with self.assertRaises(ValueError) as caught:
                with loopback.prepared_loopback():
                    raise primary
        self.assertIs(caught.exception, primary)
        self.assertEqual(addresses, {'127.0.0.1', '127.0.0.3'})
        self.assertIn('Loopback cleanup failed: 127.0.0.3', errors.getvalue())

    def test_cleanup_failure_alone_fails(self):
        _, _, command = self.environment({'127.0.0.1'}, fail_remove='127.0.0.3')
        with patch.object(loopback.sys, 'platform', 'darwin'), \
                patch.object(loopback, 'command', command), \
                patch.object(loopback, 'verify_bindings'), redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'Loopback cleanup failed'):
                with loopback.prepared_loopback():
                    pass

    def test_linux_checks_bindings_without_system_commands(self):
        with patch.object(loopback.sys, 'platform', 'linux'), \
                patch.object(loopback, 'command') as command, \
                patch.object(loopback, 'verify_bindings') as verify:
            with loopback.prepared_loopback():
                pass
            command.assert_not_called()
            verify.assert_called_once_with()

    def test_commands_are_bounded(self):
        result = subprocess.CompletedProcess(['example'], 0, '')
        with patch.object(loopback.subprocess, 'run', return_value=result) as run:
            loopback.command(['example'])
        self.assertEqual(run.call_args.kwargs['timeout'], 10)


if __name__ == '__main__':
    unittest.main()
