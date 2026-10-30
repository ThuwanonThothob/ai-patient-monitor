"""Manage the local Smart Ward stack without killing unrelated port owners.

All dependencies are loaded by the Python interpreter which invoked this file.
A private Unix control socket handles status/stop; no saved PID is trusted.
"""
import argparse
import errno
import fcntl
import importlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'

# Ensure Homebrew and standard bin directories are searchable for Node/npm
path_dirs = os.environ.get('PATH', '').split(os.pathsep)
for candidate in ('/opt/homebrew/bin', '/usr/local/bin'):
    if os.path.isdir(candidate) and candidate not in path_dirs:
        path_dirs.insert(0, candidate)
os.environ['PATH'] = os.pathsep.join(path_dirs)
RUNTIME = BACKEND / 'runtime'
CONTROL = RUNTIME / 'launcher.sock'
LOCK = RUNTIME / 'launcher.lock'
PORTS = (3000, 3001, 8000, 8001)
DEPENDENCIES = {
    'fastapi': 'fastapi', 'uvicorn': 'uvicorn[standard]', 'sklearn': 'scikit-learn',
    'numpy': 'numpy', 'joblib': 'joblib', 'google.genai': 'google-genai',
    'paho.mqtt.client': 'paho-mqtt', 'dotenv': 'python-dotenv',
    'docx': 'python-docx', 'httpx': 'httpx', 'certifi': 'certifi',
}


def say(message):
    print(message, flush=True)


def urls():
    staff = os.environ.get('WARD_STAFF_ORIGIN', 'http://localhost:3000')
    patient = os.environ.get('WARD_PATIENT_ORIGIN', 'http://localhost:3001')
    say('บุคลากร: ' + staff + ' | ผู้ป่วย: ' + patient)


def control_request(command='status', path=None):
    """Only communicate with the private socket for this exact checkout."""
    path = path or CONTROL
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(str(path))
            client.sendall(json.dumps({'command': command, 'project': str(ROOT)}).encode() + b'\n')
            data = b''
            while b'\n' not in data and len(data) < 4096:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data += chunk
        result = json.loads(data)
        if result.get('service') != 'smart-ward-launcher' or result.get('project') != str(ROOT):
            raise RuntimeError('Control socket belongs to a different service; nothing was stopped.')
        return result
    except (FileNotFoundError, ConnectionRefusedError, ConnectionResetError):
        return None
    except (json.JSONDecodeError, socket.timeout) as error:
        raise RuntimeError('ตัวเปิดระบบยังไม่ตอบสนอง ลอง --status อีกครั้ง; ไม่มีการปิดโปรแกรมอื่น') from error


class Controller:
    def __init__(self, path=None):
        self.path = path or CONTROL
        self.stop = threading.Event()
        self.closed = threading.Event()
        self.stage = 'CHECKING'
        self.socket = None
        self.thread = None
        self.bound = False
        self.path_identity = None

    def start(self):
        # Caller holds the file lock. Only a stale socket owned by this user may
        # be removed; never remove an ordinary file/symlink at this path.
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise RuntimeError('Unexpected file at launcher control path; refusing to replace it.')
            if control_request(path=self.path) is not None:
                raise RuntimeError('Another launcher is already running.')
            self.path.unlink()
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.socket.bind(str(self.path))
            self.bound = True
            info = self.path.lstat()
            self.path_identity = (info.st_dev, info.st_ino)
            self.socket.listen(4)
            self.socket.settimeout(.2)
            self.path.chmod(0o600)
        except BaseException:
            self.socket.close()
            raise
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while not self.closed.is_set():
            try:
                client, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with client:
                try:
                    client.settimeout(1)
                    data = b''
                    while b'\n' not in data and len(data) < 4096:
                        chunk = client.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    request = json.loads(data)
                    if request.get('project') != str(ROOT) or request.get('command') not in {'status', 'stop'}:
                        continue
                    if request['command'] == 'stop':
                        self.stage = 'STOPPING'
                        self.stop.set()
                    result = {'service': 'smart-ward-launcher', 'project': str(ROOT),
                              'stage': self.stage, 'pid': os.getpid()}
                    client.sendall(json.dumps(result).encode() + b'\n')
                except (OSError, ValueError):
                    continue

    def close(self):
        self.closed.set()
        if self.socket:
            self.socket.close()
        if self.thread:
            self.thread.join(timeout=2)
        if self.bound:
            self.bound = False
            try:
                info = self.path.lstat()
                if (info.st_dev, info.st_ino) == self.path_identity:
                    self.path.unlink()
            except FileNotFoundError:
                pass


def launcher_locked():
    try:
        with LOCK.open('r') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return False
            except BlockingIOError:
                return True
    except FileNotFoundError:
        return False


def occupied_ports(ports=PORTS):
    occupied = []
    for port in ports:
        with socket.socket() as probe:
            # Match server bind behavior. A recently closed connection in
            # TIME_WAIT is not a running server and must not block a restart.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(('127.0.0.1', port))
            except OSError as error:
                if error.errno == errno.EADDRINUSE:
                    occupied.append(port)
                else:
                    raise RuntimeError(f'ตรวจพอร์ต {port} ไม่ได้: {error}; ไม่ใช่ข้อยืนยันว่าพอร์ตถูกใช้อยู่') from error
    return occupied


def conflict_message(ports):
    return ('พอร์ตถูกใช้งาน: ' + ', '.join(map(str, ports)) +
            '\nไม่มีการปิดโปรแกรมอื่นอัตโนมัติ หากรัน uvicorn/Next แยกอยู่ ให้กด Ctrl+C ใน Terminal เดิมก่อน'
            '\nตรวจเจ้าของพอร์ตด้วย: lsof -nP -iTCP:' + str(ports[0]) + ' -sTCP:LISTEN')


def dependency_errors():
    errors = []
    for module, package in DEPENDENCIES.items():
        try:
            importlib.import_module(module)
        except Exception as error:
            errors.append((package, type(error).__name__))
    return errors


def check_dependencies():
    say('Python ที่ใช้: ' + sys.executable)
    errors = dependency_errors()
    if errors:
        packages = ', '.join(package + ' (' + kind + ')' for package, kind in errors)
        command = shlex.join([sys.executable, '-m', 'pip', 'install', '-r', str(BACKEND / 'requirements.txt')])
        raise RuntimeError('แพ็กเกจขาดหรือโหลดไม่ได้: ' + packages + '\nติดตั้งใน Python ตัวเดียวกันด้วย:\n' + command)
    if not shutil.which('npm'):
        raise RuntimeError('ไม่พบ npm ใน PATH กรุณาติดตั้ง Node.js/npm ก่อน')
    if not (ROOT / 'frontend/node_modules/next').exists():
        raise RuntimeError('ยังไม่มี frontend dependencies รัน: npm --prefix frontend install')
    say('Python dependencies และ Next.js: พร้อม')


class StartupCancelled(Exception):
    pass


class Stack:
    def __init__(self, controller, production=False):
        self.controller = controller
        self.production = production
        self.children = []
        self.logs = []
        self.env = {**os.environ,
                    'WARD_DB_PATH': os.environ.get('WARD_DB_PATH', str(RUNTIME / 'ward-demo.db')),
                    'WARD_BEDSIDE_MQTT_ENABLED': os.environ.get('WARD_BEDSIDE_MQTT_ENABLED', '0'),
                    'PYTHONDONTWRITEBYTECODE': '1'}
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def check_stop(self):
        if self.controller.stop.is_set():
            raise StartupCancelled()

    def spawn(self, name, command, cwd):
        self.check_stop()
        self.controller.stage = 'STARTING ' + name
        log_path = RUNTIME / 'logs' / (name + '.log')
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open('a', encoding='utf-8')
        self.logs.append(handle)
        handle.write('\n--- ' + time.strftime('%Y-%m-%d %H:%M:%S') + ' ---\n')
        handle.flush()
        child = subprocess.Popen(command, cwd=cwd, env=self.env,
                                 stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        self.children.append((name, child, log_path))
        return child, log_path

    def prepare(self, module, label):
        say(label + '…')
        child, log_path = self.spawn(module.rsplit('.', 1)[-1], [sys.executable, '-m', module], BACKEND)
        while child.poll() is None:
            self.check_stop()
            self.controller.stop.wait(.2)
        if child.returncode:
            raise RuntimeError(label + ' ไม่สำเร็จ ดูรายละเอียด: ' + str(log_path))

    def service(self, name, command, cwd, port, audience=None):
        say('กำลังเปิด ' + name + ' ที่พอร์ต ' + str(port) + '…')
        child, log_path = self.spawn(name, command, cwd)
        endpoint = '/health' if audience else '/'
        deadline = time.monotonic() + 75
        while True:
            self.check_stop()
            if child.poll() is not None:
                raise RuntimeError(name + ' ปิดตัวก่อนพร้อมใช้งาน ดู log: ' + str(log_path))
            try:
                with self.http.open(f'http://127.0.0.1:{port}' + endpoint, timeout=2) as response:
                    if audience:
                        data = json.loads(response.read(4096))
                        if data.get('portal') != audience or data.get('status') != 'ok':
                            raise RuntimeError('Unexpected API on port ' + str(port))
                    else:
                        response.read(1)
                say('พร้อม: ' + name)
                return
            except (OSError, ValueError):
                if time.monotonic() > deadline:
                    raise RuntimeError(name + ' ใช้เวลาเริ่มนานเกินกำหนด ดู log: ' + str(log_path))
                self.controller.stop.wait(.2)

    def start(self):
        if self.production:
            for audience in ('staff', 'patient'):
                if not (ROOT / 'frontend' / ('.next-' + audience) / 'BUILD_ID').is_file():
                    raise RuntimeError('Build both portals first: npm --prefix frontend run build && npm --prefix frontend run build:patient')
            if not (BACKEND / 'models/bidmc_monitor_v1.joblib').is_file():
                raise RuntimeError('Prepare and validate the model before starting production bundles')
        if not (BACKEND / 'data/raw/bidmc/manifest.json').exists():
            self.prepare('ml_pipeline.download_bidmc', 'ดาวน์โหลด BIDMC')
        if not (BACKEND / 'models/bidmc_monitor_v1.joblib').exists():
            self.prepare('ml_pipeline.train_bidmc', 'เทรนโมเดล BIDMC')
        for audience, app, port in [('staff', 'main:app', 8000), ('patient', 'patient_api:app', 8001)]:
            self.service('backend-' + audience,
                         [sys.executable, '-m', 'uvicorn', app, '--host', '127.0.0.1', '--port', str(port)],
                         BACKEND, port, audience)
        # These MUST be sequential: both Next instances generate next-env.d.ts.
        for audience, port in [('staff', 3000), ('patient', 3001)]:
            self.service('frontend-' + audience, ['npm', 'run', ('start:' if self.production else 'dev:') + audience], ROOT / 'frontend', port)
        self.controller.stage = 'RUNNING'
        say('\nSmart Ward พร้อมใช้งาน')
        urls()
        say('รหัสบุคลากร: backend/.staff-password (หรือ WARD_STAFF_PASSWORD)')
        say('AI รอข้อมูลต่อเนื่องประมาณ 60–70 วินาที; ดู log ใน backend/runtime/logs/')
        say('เปิด Terminal นี้ค้างไว้ | หยุด: Ctrl+C หรือ python3 scripts/run_ward.py --stop')
        services = self.children[-4:]
        while not self.controller.stop.wait(.5):
            for name, child, log_path in services:
                if child.poll() is not None:
                    raise RuntimeError(name + ' หยุดทำงาน ดู log: ' + str(log_path))

    def close(self):
        self.controller.stage = 'STOPPING'
        # Signal only Popen handles created in THIS process, never PIDs found
        # by scanning a port or read from a stale state file.
        for _, child, _ in self.children:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 8
        for _, child, _ in self.children:
            try:
                child.wait(timeout=max(.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=3)
        for handle in self.logs:
            handle.close()


def stop_managed():
    state = control_request('stop')
    if state is None:
        if launcher_locked():
            raise RuntimeError('มีอีก Terminal กำลังเริ่มระบบ รอสักครู่แล้วลอง --stop อีกครั้ง')
        ports = occupied_ports()
        if ports:
            raise RuntimeError('ไม่พบชุดที่เปิดด้วย launcher นี้\n' + conflict_message(ports))
        say('ระบบหยุดอยู่แล้ว พอร์ตทั้งหมดว่าง')
        return
    say('กำลังหยุดเฉพาะเซิร์ฟเวอร์ของ Smart Ward…')
    deadline = time.monotonic() + 20
    while control_request() is not None or launcher_locked():
        if time.monotonic() > deadline:
            raise RuntimeError('ยังหยุดไม่เสร็จ ลอง --status; ไม่มีการปิดโปรแกรมอื่น')
        time.sleep(.2)
    say('หยุดชุดเดิมเรียบร้อย')


def run(argv=None):
    parser = argparse.ArgumentParser(description='เปิด/ตรวจสอบ/หยุด Smart Ward ทั้งสี่เซิร์ฟเวอร์')
    parser.add_argument('--production', action='store_true', help='ใช้ production builds ที่เตรียมไว้ แทน development server')
    parser.add_argument('--env-file', type=Path, help='โหลดค่ารัน เช่น backend/runtime/private-test.env')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--start', action='store_true', help='เปิดระบบ Smart Ward')
    group.add_argument('--status', action='store_true', help='แสดงสถานะ ไม่เปิดเซิร์ฟเวอร์เพิ่ม')
    group.add_argument('--stop', action='store_true', help='หยุดเฉพาะชุดที่ launcher นี้เปิด')
    group.add_argument('--restart', action='store_true', help='หยุดชุดเดิมแล้วเปิดใหม่ใน Terminal นี้')
    group.add_argument('--check', action='store_true', help='ตรวจ dependencies และพอร์ต โดยไม่เปิดระบบ')
    args = parser.parse_args(argv)
    if args.env_file:
        if not args.env_file.is_file():
            raise RuntimeError('ไม่พบไฟล์ตั้งค่า: ' + str(args.env_file))
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=True)
    if args.stop:
        stop_managed()
        return 0
    if args.restart:
        stop_managed()
    state = control_request()
    if args.status:
        if state:
            say('Smart Ward: ' + state['stage'])
            urls()
        else:
            ports = occupied_ports()
            say(conflict_message(ports) if ports else 'Smart Ward ยังไม่ได้เปิด พอร์ตทั้งหมดว่าง')
        return 0
    if state and not args.check:
        say('ชุดเดิมกำลังทำงานอยู่ (' + state['stage'] + ') ไม่ต้องเปิดซ้ำ')
        urls()
        say('เริ่มใหม่: python3 scripts/run_ward.py --restart')
        say('หยุด: python3 scripts/run_ward.py --stop')
        return 0
    if args.check:
        check_dependencies()
        ports = occupied_ports()
        say(('ชุดเดิม: ' + state['stage']) if state else (conflict_message(ports) if ports else 'พอร์ตทั้งหมดว่าง'))
        return 0 if state or not ports else 1

    RUNTIME.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            say('มีอีก Terminal กำลังเปิด/ปิดระบบ รอสักครู่แล้วใช้ --status')
            return 0
        controller = Controller()
        stack = Stack(controller, production=args.production)
        previous_handlers = {}
        try:
            controller.start()
            for kind in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[kind] = signal.signal(kind, lambda *_: controller.stop.set())
            check_dependencies()
            stack.check_stop()
            ports = occupied_ports()
            if ports:
                raise RuntimeError(conflict_message(ports))
            stack.start()
        except (StartupCancelled, KeyboardInterrupt):
            pass
        finally:
            try:
                stack.close()
            finally:
                controller.close()
                for kind, handler in previous_handlers.items():
                    signal.signal(kind, handler)
        say('หยุด Smart Ward แล้ว')
    return 0


def main():
    try:
        return run()
    except (RuntimeError, OSError) as error:
        say('\nเปิดระบบไม่สำเร็จ: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
