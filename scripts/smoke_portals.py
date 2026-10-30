"""Integration and smoke check against dual frontend and backend ports.
Never logs or prints credentials.
"""
import asyncio
import json
import os
from pathlib import Path
import httpx
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]

STAFF_ONLY_ENDPOINTS = [
    '/api/monitor/patients',
    '/api/monitor/status',
    '/api/agent/status',
    '/api/ward/summary',
    '/api/patient/A001/details',
]


async def run():
    password_file = ROOT / 'backend/.staff-password'
    password = os.getenv('WARD_STAFF_PASSWORD') or (password_file.read_text().strip() if password_file.is_file() else '')

    async with httpx.AsyncClient(base_url='http://localhost:8000', timeout=45) as backend_staff, \
               httpx.AsyncClient(base_url='http://localhost:8001', timeout=45) as backend_patient, \
               httpx.AsyncClient(base_url='http://localhost:3000', timeout=45) as staff, \
               httpx.AsyncClient(base_url='http://localhost:3001', timeout=45) as patient:

        # -------------------------------------------------------------
        # 1. System Health Checks (Port 8000 & 8001)
        # -------------------------------------------------------------
        # Backend Staff /health
        res_health_staff = await backend_staff.get('/health')
        assert res_health_staff.status_code == 200, f"Backend staff /health returned {res_health_staff.status_code}"
        assert res_health_staff.json() == {'status': 'ok', 'portal': 'staff'}

        # Backend Patient /health
        res_health_patient = await backend_patient.get('/health')
        assert res_health_patient.status_code == 200, f"Backend patient /health returned {res_health_patient.status_code}"
        assert res_health_patient.json() == {'status': 'ok', 'portal': 'patient'}

        # Probe healthz endpoint on port 8000
        res_healthz = await backend_staff.get('/healthz')
        assert res_healthz.status_code in (200, 401), f"Unexpected /healthz status code: {res_healthz.status_code}"

        # -------------------------------------------------------------
        # 2. Frontend Accessibility Checks (Port 3000 & 3001)
        # -------------------------------------------------------------
        staff_ui = await staff.get('/')
        assert staff_ui.status_code == 200, f"Staff Dashboard (3000) returned {staff_ui.status_code}"
        assert '<!DOCTYPE html>' in staff_ui.text or '<html' in staff_ui.text, "Staff Dashboard did not return HTML"

        patient_ui = await patient.get('/')
        assert patient_ui.status_code == 200, f"Patient Portal (3001) returned {patient_ui.status_code}"
        assert '<!DOCTYPE html>' in patient_ui.text or '<html' in patient_ui.text, "Patient Portal did not return HTML"

        # -------------------------------------------------------------
        # 3. Security Check: Patient Port 8001 Strictly Rejects Staff APIs
        # -------------------------------------------------------------
        # Unauthenticated calls to patient port 8001 for staff endpoints must be rejected
        for endpoint in STAFF_ONLY_ENDPOINTS:
            res_unauth = await backend_patient.get(endpoint)
            assert res_unauth.status_code in (401, 404), (
                f"Patient port 8001 did not reject unauthenticated staff API {endpoint}: got {res_unauth.status_code}"
            )

        # Cross-Origin: Staff Origin on Patient Port 8001 must return 403 Forbidden
        res_cross_origin = await backend_patient.get('/api/session/config', headers={'Origin': 'http://localhost:3000'})
        assert res_cross_origin.status_code == 403, (
            f"Patient port 8001 did not block staff origin: got {res_cross_origin.status_code}"
        )

        # -------------------------------------------------------------
        # 4. Authentication & Session Scope Verification
        # -------------------------------------------------------------
        assert (await staff.get('/api/monitor/patients')).status_code == 401
        assert (await staff.post('/api/session/login', json={'password': password}, headers={'Origin': 'http://localhost:3000'})).status_code == 200
        assert (await patient.post('/api/session/login', json={'patient_id': 'A001'}, headers={'Origin': 'http://localhost:3001'})).status_code == 200

        try:
            # Patient session scope: asking for B001 returns session identity A001
            me = (await patient.get('/api/me?patient_id=B001')).json()
            assert me['patient_id'] == 'A001'

            # Authenticated patient calling staff endpoints must return 404 Not Found
            for endpoint in STAFF_ONLY_ENDPOINTS:
                res_patient_staff = await patient.get(endpoint)
                assert res_patient_staff.status_code == 404, (
                    f"Patient portal unexpectedly resolved staff endpoint {endpoint}: got {res_patient_staff.status_code}"
                )

            # Staff cross-origin check
            assert (await staff.get('/api/monitor/status', headers={'Origin': 'http://localhost:3001'})).status_code == 403

            # Staff monitor status & bed list
            state = (await staff.get('/api/monitor/status')).json()
            beds = (await staff.get('/api/monitor/patients')).json()['patients']
            assert len(beds) == 60
            assert state['status'] == 'RUNNING', state

            detail = (await staff.get('/api/patient/A001/details')).json()
            assert detail['risk_model']['status'] == 'UNSUPPORTED_CONTEXT'

            # WebSocket vitals proxy verification
            cookie = '; '.join(name + '=' + value for name, value in staff.cookies.items())
            async with connect('ws://localhost:3000/ws/vitals', origin='http://localhost:3000',
                               additional_headers={'Cookie': cookie}, open_timeout=15) as stream:
                reading = json.loads(await asyncio.wait_for(stream.recv(), timeout=15))
                assert 'patient_id' in reading

            summary = {
                'backend_staff_port': 8000,
                'backend_patient_port': 8001,
                'frontend_staff_port': 3000,
                'frontend_patient_port': 3001,
                'health_endpoints': {'port_8000': 'passed', 'port_8001': 'passed', 'healthz_probe': 'passed'},
                'patient_port_isolation': 'verified',
                'worker_status': state['status'],
                'registered_beds': len(beds),
                'fresh_beds': state['fresh_beds'],
                'ready_models': sum(row['analysis']['status'] == 'READY' for row in beds),
                'patient_session': me['patient_id'],
                'websocket_proxy': 'passed',
                'result': 'ALL_SMOKE_TESTS_PASSED'
            }
            print(json.dumps(summary, indent=2))
        finally:
            await staff.post('/api/session/logout')
            await patient.post('/api/session/logout')


if __name__ == '__main__':
    asyncio.run(run())
