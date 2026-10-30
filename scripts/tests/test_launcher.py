"""Launcher lifecycle regressions; no application database or API keys used."""
from contextlib import redirect_stdout
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('ward_launcher', Path(__file__).resolve().parents[1] / 'run_ward.py')
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ward-', dir='/tmp')
        self.root = Path(self.temp.name)
        self.socket_path = self.root / 'launcher.sock'
        self.controller = launcher.Controller(self.socket_path)

    def tearDown(self):
        self.controller.close()
        self.temp.cleanup()

    def test_status_and_stop_use_private_control_socket(self):
        self.controller.start()
        self.controller.stage = 'RUNNING'
        state = launcher.control_request(path=self.socket_path)
        self.assertEqual(state['stage'], 'RUNNING')
        self.assertEqual(stat.S_IMODE(self.socket_path.stat().st_mode), 0o600)
        launcher.control_request('stop', self.socket_path)
        self.assertTrue(self.controller.stop.is_set())

    def test_stale_socket_can_be_recovered(self):
        with socket.socket(socket.AF_UNIX) as old:
            old.bind(str(self.socket_path))
        self.assertIsNone(launcher.control_request(path=self.socket_path))
        self.controller.start()
        self.assertEqual(launcher.control_request(path=self.socket_path)['service'], 'smart-ward-launcher')

    def test_ordinary_file_is_never_deleted(self):
        self.socket_path.write_text('unrelated file')
        with self.assertRaises(RuntimeError):
            self.controller.start()
        self.controller.close()
        self.assertEqual(self.socket_path.read_text(), 'unrelated file')

    def test_symlink_is_never_replaced(self):
        target = self.root / 'keep.txt'
        target.write_text('keep')
        self.socket_path.symlink_to(target)
        with self.assertRaises(RuntimeError):
            self.controller.start()
        self.controller.close()
        self.assertTrue(self.socket_path.is_symlink())
        self.assertEqual(target.read_text(), 'keep')

    def test_live_socket_is_never_replaced_by_second_controller(self):
        self.controller.start()
        second = launcher.Controller(self.socket_path)
        with self.assertRaises(RuntimeError):
            second.start()
        second.close()
        self.assertIsNotNone(launcher.control_request(path=self.socket_path))

    def test_repeated_cleanup_does_not_delete_a_new_file(self):
        self.controller.start()
        self.controller.close()
        self.socket_path.write_text('new unrelated file')
        self.controller.close()
        self.assertEqual(self.socket_path.read_text(), 'new unrelated file')


class PreflightTests(unittest.TestCase):
    def test_duplicate_start_is_success_without_spawning(self):
        state = {'stage': 'RUNNING'}
        with patch.object(launcher, 'control_request', return_value=state), patch.object(launcher, 'Stack') as stack, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(launcher.run([]), 0)
            stack.assert_not_called()
            self.assertIn('http://localhost:3000', output.getvalue())

    def test_stop_never_kills_an_unmanaged_port_owner(self):
        with patch.object(launcher, 'control_request', return_value=None), patch.object(launcher, 'launcher_locked', return_value=False), patch.object(launcher, 'occupied_ports', return_value=[3000]), patch.object(launcher.os, 'killpg') as kill:
            with self.assertRaisesRegex(RuntimeError, '3000'):
                launcher.stop_managed()
            kill.assert_not_called()

    def test_missing_dependencies_are_collected_together(self):
        def check(module):
            if module in ('docx', 'certifi'):
                raise ModuleNotFoundError(module)
        with patch.object(launcher.importlib, 'import_module', side_effect=check):
            self.assertEqual([name for name, _ in launcher.dependency_errors()], ['python-docx', 'certifi'])

    def test_install_message_uses_the_running_interpreter(self):
        with patch.object(launcher, 'dependency_errors', return_value=[('python-docx', 'ModuleNotFoundError')]), redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError) as error:
                launcher.check_dependencies()
            self.assertIn(sys.executable, str(error.exception))
            self.assertIn('python-docx', str(error.exception))

    def test_active_listener_is_detected_without_stopping_it(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen(1)
            port = server.getsockname()[1]
            self.assertEqual(launcher.occupied_ports([port]), [port])
            with socket.create_connection(('127.0.0.1', port), timeout=2):
                connection, _ = server.accept()
                connection.close()

    def test_recently_closed_connection_does_not_block_restart(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('127.0.0.1', 0))
            server.listen(1)
            port = server.getsockname()[1]
            with socket.create_connection(('127.0.0.1', port), timeout=2) as client:
                connection, _ = server.accept()
                connection.close()  # Server's accepted socket enters TIME_WAIT.
                self.assertEqual(client.recv(1), b'')
        self.assertEqual(launcher.occupied_ports([port]), [])

    def test_permission_error_is_not_misreported_as_port_in_use(self):
        with patch.object(launcher.socket, 'socket') as socket_factory:
            probe = socket_factory.return_value.__enter__.return_value
            probe.bind.side_effect = OSError(errno.EPERM, 'Operation not permitted')
            with self.assertRaisesRegex(RuntimeError, 'ไม่ใช่ข้อยืนยัน'):
                launcher.occupied_ports([3000])

    def test_foreign_control_response_is_rejected(self):
        with patch.object(launcher.socket, 'socket') as socket_factory:
            client = socket_factory.return_value.__enter__.return_value
            client.recv.return_value = json.dumps({'service': 'other', 'project': str(launcher.ROOT)}).encode() + b'\n'
            with self.assertRaisesRegex(RuntimeError, 'different service'):
                launcher.control_request()

    def test_empty_stack_does_not_signal_any_process(self):
        controller = launcher.Controller(Path('/tmp/not-created-ward-test.sock'))
        stack = launcher.Stack(controller)
        with patch.object(launcher.os, 'killpg') as kill:
            stack.close()
            kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
