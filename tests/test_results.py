"""Reject tampered raw evidence before reporting model findings."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.verify_results import verify


class ResultVerificationTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).resolve().parents[1] / 'results/kaggle-2026-10-08/results.json'
        self.data = json.loads(self.path.read_text(encoding='utf-8'))

    def test_published_real_results_have_complete_verified_coverage(self):
        self.assertEqual(450, verify(self.path)['verified_rows'])

    def reject_modified(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'results.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(AssertionError):
                verify(path)

    def test_modified_response_is_rejected(self):
        self.data['rows'][0]['response'] += ' altered'
        self.reject_modified(self.data)

    def test_duplicate_and_missing_cases_are_rejected(self):
        self.data['rows'][-1] = self.data['rows'][0]
        self.reject_modified(self.data)
