"""Verify a mixed complete/partial build export without calling it complete."""
import hashlib
import json
from pathlib import Path

from trustboundary.dataset import dataset_hash, generate_cases
from trustboundary.scoring import score
from tools.verify_results import verify


def main():
    source = Path('outputs/kaggle-build-export/trustboundary-combined')
    data = json.loads((source / 'results.json').read_text())
    cases = {c['id']: c for c in generate_cases(50)}
    assert data['metadata']['dataset_sha256'] == dataset_hash(list(cases.values()))
    seen, groups = set(), {}
    for row in data['rows']:
        key = row['model'], row['case_id']
        assert key not in seen
        seen.add(key)
        case = cases[row['case_id']]
        assert row['execution_mode'] == 'kaggle'
        assert hashlib.sha256(row['response'].encode()).hexdigest() == row['response_sha256']
        assert hashlib.sha256(case['prompt'].encode()).hexdigest() == row['prompt_sha256']
        assert score(case, row['response']) == row['score']
        groups.setdefault(row['model'], []).append(row)
    complete = [m for m, rows in groups.items()
                if {r['case_id'] for r in rows} == set(cases)
                and all(not r['transport_error'] for r in rows)]
    target = Path('results/kaggle-2026-10-08-build')
    target.mkdir(parents=True, exist_ok=True)
    (target / 'partial-inclusive-raw.json').write_text(json.dumps(data, indent=2))
    selected = {**data, 'metadata': {**data['metadata'], 'model_results_complete': True,
                'selection_note': 'Only complete models; partial Claude run preserved separately.'},
                'rows': [r for r in data['rows'] if r['model'] in complete]}
    (target / 'results.json').write_text(json.dumps(selected, indent=2))
    checked = verify(target / 'results.json')
    checked['partial_models'] = {m: {'rows': len(rows),
        'transport_error_classes': sorted({r['transport_error'] for r in rows if r['transport_error']})}
        for m, rows in groups.items() if m not in complete}
    (target / 'verification.json').write_text(json.dumps(checked, indent=2))
    for model, metrics in checked['primary'].items():
        print(model, metrics['n'], metrics['safe_completion'])
    print('Partial models:', checked['partial_models'])


if __name__ == '__main__':
    main()
