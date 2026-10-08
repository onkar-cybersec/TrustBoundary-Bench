"""Offline SDK contract shim. These tests do not validate remote Kaggle access."""
from contextlib import nullcontext
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from trustboundary.cli import fixture_plan
from trustboundary.dataset import generate_cases


class FakeModel:
    name = 'offline-contract-shim'

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail
        self.answers = {c['prompt']: fixture_plan(c, 'oracle-fixture') for c in generate_cases(2)}

    def prompt(self, prompt):
        self.calls += 1
        if self.fail:
            raise PermissionError('Never expose this fake credential in errors')
        return self.answers[prompt]


class AdapterTests(unittest.TestCase):
    def setUp(self):
        fake_sdk = types.ModuleType('kaggle_benchmarks')
        fake_sdk.task = lambda **kwargs: lambda func: func
        fake_sdk.chats = types.SimpleNamespace(new=lambda name: nullcontext())
        fake_sdk.llms = {'offline-contract-shim': FakeModel()}
        self.modules_patch = patch.dict(sys.modules, {'kaggle_benchmarks': fake_sdk})
        self.modules_patch.start()
        sys.modules.pop('trustboundary.kaggle_adapter', None)
        self.adapter = importlib.import_module('trustboundary.kaggle_adapter')
        self.original_cwd = Path.cwd()
        self.directory = tempfile.TemporaryDirectory()
        os.chdir(self.directory.name)

    def tearDown(self):
        os.chdir(self.original_cwd)
        self.directory.cleanup()
        sys.modules.pop('trustboundary.kaggle_adapter', None)
        self.modules_patch.stop()

    def test_saves_reproducible_outputs_and_resumes_without_calls(self):
        model = FakeModel()
        self.assertEqual(1.0, self.adapter.authority_benchmark(model, 2))
        self.assertEqual(6, model.calls)
        result_file = next(Path('trustboundary-results').glob('*/results.json'))
        data = json.loads(result_file.read_text(encoding='utf-8'))
        self.assertTrue(data['metadata']['model_results_complete'])
        self.assertEqual(6, len(data['rows']))
        self.assertTrue(all('prompt_sha256' in row for row in data['rows']))
        self.assertEqual(1.0, self.adapter.authority_benchmark(model, 2))
        self.assertEqual(6, model.calls)

    def test_transport_failure_stops_with_partial_artifact_and_no_secret(self):
        model = FakeModel(fail=True)
        with self.assertRaisesRegex(RuntimeError, 'PermissionError'):
            self.adapter.authority_benchmark(model, 2)
        self.assertEqual(1, model.calls)
        result_file = next(Path('trustboundary-results').glob('*/results.json'))
        data = json.loads(result_file.read_text(encoding='utf-8'))
        self.assertFalse(data['metadata']['model_results_complete'])
        self.assertNotIn('fake credential', result_file.read_text(encoding='utf-8'))
        model.fail = False
        self.assertEqual(1.0, self.adapter.authority_benchmark(model, 2))
        self.assertEqual(7, model.calls)

    def test_dataset_size_starts_separate_checkpoint(self):
        model = FakeModel()
        self.adapter.authority_benchmark(model, 1)
        self.adapter.authority_benchmark(model, 2)
        self.assertEqual(9, model.calls)
        self.assertEqual(2, len(list(Path('trustboundary-results').glob('*/checkpoint.json'))))


if __name__ == '__main__':
    unittest.main()
