"""Verified, held-out pressure-map evidence. No clinical or live sensor actions."""
import hashlib
import json
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from research_api import EvidenceStore

ROOT = Path(__file__).resolve().parent / 'models/posture'
router = APIRouter(prefix='/api/research/posture', tags=['posture-research-only'])


class PostureStore(EvidenceStore):
    def load(self):
        try:
            return super().load()
        except HTTPException as error:
            raise HTTPException(503, 'PMD artifacts unavailable or invalid; download_pmd then train_posture in backend') from error

    def case(self, case_id, report):
        if not re.fullmatch(r'S\d{1,2}-P[123]-F\d+', case_id):
            raise HTTPException(404, 'Unknown held-out PMD case')
        entry = next((item for item in report['cases'] if item['id'] == case_id), None)
        if entry is None or entry['subject'] not in report['splits']['test']:
            raise HTTPException(404, 'Only held-out PMD subjects are available')
        try:
            content = (self.root / report['run_id'] / 'cases' / (case_id + '.json')).read_bytes()
            if hashlib.sha256(content).hexdigest() != entry['sha256']:
                raise ValueError('Case integrity failure')
            return json.loads(content)
        except (OSError, ValueError) as error:
            raise HTTPException(503, 'PMD case integrity failure') from error


store = PostureStore(ROOT)


@router.get('/status')
def status():
    try:
        report = store.load()
        return {'status': 'READY', **{key: value for key, value in report.items() if key != 'cases'}}
    except HTTPException as error:
        return {'status': 'UNAVAILABLE', 'live_enabled': False, 'message': error.detail}


@router.get('/cases')
def cases(outcome: str = Query('all', pattern='^(all|correct|incorrect|abstained)$')):
    report = store.load()
    items = [item for item in report['cases'] if outcome == 'all'
             or (outcome == 'correct' and item['correct'] and not item['abstained'])
             or (outcome == 'incorrect' and not item['correct'] and not item['abstained'])
             or (outcome == 'abstained' and item['abstained'])]
    # Deliberately omit position/frame/source filename: positions encode ground truth.
    # Opaque sequential references keep the blind default view genuinely unlabelled.
    index = {item['id']: n for n, item in enumerate(report['cases'])}
    return {'run_id': report['run_id'], 'total': len(items), 'cases': [
        {'ref': index[item['id']], 'subject': item['subject']} for item in items]}


@router.get('/cases/{case_ref}')
def case(case_ref: int, reveal: bool = False):
    report = store.load()
    if not 0 <= case_ref < len(report['cases']):
        raise HTTPException(404, 'Unknown PMD case')
    payload = store.case(report['cases'][case_ref]['id'], report)
    visible = {key: value for key, value in payload.items()
               if key not in {'id', 'position', 'frame', 'source_file', 'label'}}
    if reveal:
        visible.update({key: payload[key] for key in ('id', 'position', 'frame', 'source_file', 'label')})
    return {**visible, 'ref': case_ref, 'run_id': report['run_id'], 'selected_model': report['selected_model'],
            'research_only': True, 'live_enabled': False}


@router.get('/report', response_class=PlainTextResponse)
def report_text():
    report = store.load()
    return PlainTextResponse(json.dumps({k: v for k, v in report.items() if k != 'cases'}, ensure_ascii=False, indent=2),
        headers={'Content-Disposition': 'attachment; filename="posture-research-evidence.txt"', 'Cache-Control': 'no-store'})
