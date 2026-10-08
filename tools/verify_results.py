"""Verify public raw artifacts and report a separately labeled format sensitivity check."""
import hashlib
import json
from pathlib import Path
import re
import sys

from trustboundary.dataset import dataset_hash, generate_cases
from trustboundary.metrics import summarize
from trustboundary.scoring import score


def verify(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    cases = {c['id']: c for c in generate_cases(50)}
    assert data['metadata']['dataset_sha256'] == dataset_hash(list(cases.values()))
    assert data['metadata']['model_results_complete'] is True
    seen, groups, normalized = set(), {}, {}
    for row in data['rows']:
        key = (row['model'], row['case_id'])
        assert key not in seen, 'duplicate model/case'
        seen.add(key)
        case = cases[row['case_id']]
        assert row['execution_mode'] == 'kaggle' and not row['transport_error']
        assert hashlib.sha256(row['response'].encode()).hexdigest() == row['response_sha256']
        assert hashlib.sha256(case['prompt'].encode()).hexdigest() == row['prompt_sha256']
        assert score(case, row['response']) == row['score'], 'score mismatch'
        groups.setdefault(row['model'], []).append(row)
        # Post-hoc diagnostic only. Do not modify raw output or primary scores.
        match = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', row['response'].strip(), re.S)
        text = match.group(1) if match else row['response']
        normalized.setdefault(row['model'], []).append({**row, 'score': score(case, text)})
    for rows in groups.values():
        assert {r['case_id'] for r in rows} == set(cases), 'incomplete model'
    return {'verified_rows': len(seen), 'primary': {m: summarize(r) for m, r in groups.items()},
            'post_hoc_outer_json_fence_removal': {m: summarize(r) for m, r in normalized.items()},
            'diagnostic_note': 'Only one complete outer Markdown JSON fence is removed. '
            'This post-hoc sensitivity analysis is not the primary Kaggle score or a new model run.'}


if __name__ == '__main__':
    print(json.dumps(verify(sys.argv[1]), indent=2))
