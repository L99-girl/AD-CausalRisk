"""Synthetic fits only. Never discover or load private model/data paths."""
from copy import deepcopy
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from adni_algorithm_candidates import StrictHazards, NotEstimable
from research_runtime.discrete import person_period, predict_cif
from research_runtime.estimators import BASE, ADDED, FAMILIES, SPECS, information_arm, make_candidate
from research_runtime.inference import (SCHEMA, UNITS, ROLES, RUNTIME_DEPENDENCIES,
    read_json_bytes, validate_request, load_final_model, run_acceptance)


def request(spec='seven', family='logistic'):
    values = (72, 14, 26, 1.5, .5, 18, 4, 1, 3200, 3300)
    features = {name: {'value': value, 'unit': UNITS[name], 'measuredDate': '2020-01-01',
                       'availableDate': None, 'source': 'SYNTHETIC', 'qc': 'SYNTHETIC'}
                for name, value in zip(SPECS[spec], values)}
    return {'schemaVersion': SCHEMA, 'purpose': 'SYNTHETIC_ACCEPTANCE', 'specification': spec,
            'family': family, 'dataVersion': 'synthetic-fixture-v1', 'indexDate': '2020-01-02',
            'predictionWindowMonths': 24,
            'records': [{'subjectCode': 'SYNTHETIC-001', 'features': features}]}


def cohort():
    rng = np.random.default_rng(17)
    frame = pd.DataFrame(rng.normal(size=(36, 10)), columns=BASE+ADDED)
    frame['subject_id'] = ['SYNTHETIC-'+str(i) for i in range(len(frame))]
    frame['observed_month'] = np.tile([24, 12, 6], 12)
    frame['event_type'] = np.tile([0, 1, 2], 12)
    frame.loc[::4, list(ADDED)] = np.nan
    frame.loc[::5, 'mmse'] = np.nan
    return frame


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.models = {}
        cls.manifests = {}
        software = {name: version(name) for name in RUNTIME_DEPENDENCIES}
        frame = cohort()
        with threadpool_limits(limits=1):
            for spec in SPECS:
                folder = cls.root/spec
                folder.mkdir()
                manifest = {'features': list(SPECS[spec]), 'software': software, 'plan_sha256': 'a'*64,
                    'training_complete': True, 'clinical_use': False, 'default_model_changed': False,
                    'calibrated': False, 'final_models': [], 'models': []}
                for family in FAMILIES:
                    model = make_candidate(family, spec)
                    work = information_arm(frame, spec)
                    x, y = person_period(work, list(SPECS[spec]))
                    model.fit(x, y)  # Exactly nine small synthetic fits in this suite.
                    cls.models[spec, family] = model
                    filename = f'final__{family}'+('' if spec == 'seven' else '__'+spec)+'.joblib'
                    bundle = {'role': ROLES[spec], 'family': family, 'columns': list(SPECS[spec]),
                              'model': model, 'clinical_use': False, 'arm': spec,
                              'training_plan_sha256': 'a'*64, 'plan_sha256': 'a'*64,
                              'recommended_research_policy': 'raw', 'exact_asof_certified': False,
                              'retrospective_only': True, 'prediction_policy': 'raw_uncalibrated_24month_CIF',
                              'calibrator': {'intercept': 99, 'slope': 99}}
                    joblib.dump(bundle, folder/filename, compress=3)
                    artifact = {'file': filename, 'sha256': sha(folder/filename),
                                'family': family, 'arm': spec, 'role': ROLES[spec]}
                    manifest['models'].append(artifact)
                    manifest['final_models'].append({'family': family, 'artifact': artifact,
                                                     'recommended_research_policy': 'raw'})
                path = folder/'Model_Manifest.json'
                path.write_text(json.dumps(manifest), encoding='utf-8')
                cls.manifests[spec] = (path, sha(path))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_nine_fitted_specs_load_and_reproduce_both_raw_cifs(self):
        for spec in SPECS:
            for family in FAMILIES:
                with self.subTest(spec=spec, family=family):
                    req = request(spec, family)
                    before = deepcopy(req)
                    result = run_acceptance(req, *self.manifests[spec])
                    frame, _ = validate_request(req)
                    direct = predict_cif(self.models[spec, family], frame, list(SPECS[spec]))
                    self.assertEqual(result['predictions'], direct.to_dict(orient='records'))
                    self.assertEqual(req, before)
                    self.assertFalse(result['clinicalUse'])
                    self.assertFalse(result['defaultModelChanged'])
                    self.assertEqual(result['predictionPolicy'], 'raw')

    def test_training_medians_come_from_training_person_months(self):
        frame = cohort()
        x, _ = person_period(frame, list(BASE))
        actual = self.models['seven', 'logistic'].named_steps['preprocess'].named_transformers_[
            'clinical'].named_steps['impute'].statistics_
        np.testing.assert_array_equal(actual, np.nanmedian(x[list(BASE)].to_numpy(), axis=0))

    def test_availability_control_zeros_observed_only_and_preserves_input(self):
        original = cohort()
        before = original.copy(deep=True)
        transformed = information_arm(original, 'modality_availability')
        pd.testing.assert_frame_equal(original, before)
        pd.testing.assert_frame_equal(original[list(ADDED)].isna(), transformed[list(ADDED)].isna())
        self.assertTrue((transformed[list(ADDED)].fillna(0).to_numpy() == 0).all())
        pd.testing.assert_frame_equal(original[list(BASE)], transformed[list(BASE)])

    def test_person_month_labels_only_occur_in_final_observed_month(self):
        f = cohort().iloc[:3].copy()
        x, y = person_period(f, list(BASE))
        self.assertEqual(len(x), 42)
        self.assertEqual(np.flatnonzero(y).tolist(), [35, 41])
        self.assertEqual(y[[35, 41]].tolist(), [1, 2])

    def test_failed_refit_discards_previous_fitted_state(self):
        from sklearn.linear_model import LogisticRegression
        wrapped = StrictHazards(LogisticRegression())
        x = np.arange(30).reshape(10, 3)
        wrapped.fit(x, np.tile([0, 1, 2, 0, 1], 2))
        with self.assertRaises(NotEstimable):
            wrapped.fit(x, np.zeros(10))
        self.assertFalse(hasattr(wrapped, 'classes_'))
        self.assertFalse(hasattr(wrapped, 'estimator_'))

    def test_invalid_requests_are_rejected_before_any_model_load(self):
        cases = []
        for field, value in [('purpose', 'CLINICAL'), ('schemaVersion', 'deepagent-v1'),
                ('predictionWindowMonths', True), ('predictionWindowMonths', 12),
                ('family', 'auto'), ('dataVersion', 'demo-v1'), ('indexDate', '20200102')]:
            r = request(); r[field] = value; cases.append(r)
        r = request(); r['records'] *= 2; cases.append(r)
        r = request(); r['records'][0]['subjectCode'] = 'ADNI-001'; cases.append(r)
        r = request(); r['records'][0]['features']['mmse']['value'] = True; cases.append(r)
        r = request(); r['records'][0]['features']['mmse']['value'] = float('inf'); cases.append(r)
        r = request(); r['records'][0]['features']['mmse']['measuredDate'] = '2020-02-01'; cases.append(r)
        r = request(); del r['records'][0]['features']['mmse']; cases.append(r)
        r = request(); r['records'][0]['features']['mmse']['unit'] = 'normalized'; cases.append(r)
        r = request(); r['records'][0]['features']['mmse']['availableDate'] = '2019-12-31'; cases.append(r)
        r = request(); r['records'][0]['features']['mmse']['value'] = None; cases.append(r)
        r = request('multimodal_values'); r['records'][0]['features'][ADDED[0]]['value'] = 1.0; cases.append(r)
        r = request('multimodal_values'); r['records'][0]['features'][ADDED[1]]['unit'] = 'normalized'; cases.append(r)
        r = request('multimodal_values'); r['records'][0]['features'][ADDED[1]]['value'] = -1; cases.append(r)
        r = request('multimodal_values'); r['records'][0]['features'][ADDED[2]]['measuredDate'] = '2019-12-31'; cases.append(r)
        r = request('multimodal_values'); r['records'][0]['features'][ADDED[1]]['value'] = None; cases.append(r)
        r = request(); r['extra'] = 'ignored?'; cases.append(r)
        for index, req in enumerate(cases):
            with self.subTest(case=index, request_fields=list(req)), patch(
                    'research_runtime.inference.load_final_model') as loader:
                with self.assertRaises((ValueError, OverflowError)):
                    run_acceptance(req, *self.manifests['seven'])
                loader.assert_not_called()

    def test_explicit_nulls_keep_sources_and_stored_imputation(self):
        req = request('multimodal_values')
        for name in ADDED:
            req['records'][0]['features'][name].update(value=None, measuredDate=None, availableDate=None)
        result = run_acceptance(req, *self.manifests['multimodal_values'])
        self.assertEqual(result['sources'][0]['features'], req['records'][0]['features'])
        self.assertTrue(np.isfinite(result['predictions'][0]['ad_cif_24m']))

    def test_all_core_missing_is_blocked_before_loading(self):
        req = request()
        for item in req['records'][0]['features'].values():
            item.update(value=None, measuredDate=None, availableDate=None)
        with patch('research_runtime.inference.load_final_model') as loader:
            with self.assertRaisesRegex(ValueError, 'NO_CORE_INPUT'):
                run_acceptance(req, *self.manifests['seven'])
            loader.assert_not_called()

    def test_late_or_unknown_availability_is_never_certified(self):
        req = request('multimodal_values')
        for name in ADDED[1:]:
            req['records'][0]['features'][name]['availableDate'] = '2021-01-01'
        result = run_acceptance(req, *self.manifests['multimodal_values'])
        self.assertFalse(result['historicalAvailabilityCertified'])
        self.assertEqual(result['sources'][0]['features'][ADDED[1]]['availableDate'], '2021-01-01')

    def test_json_duplicate_nonfinite_size_and_encoding(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}',
                    b' '*131073, b'\xff', b'\xef\xbb\xbf{}'):
            with self.subTest(raw=raw[:20]), self.assertRaises((ValueError, UnicodeError)):
                read_json_bytes(raw)

    def test_wrong_manifest_pin_and_artifact_corruption_never_unpickle(self):
        path, pin = self.manifests['seven']
        with patch('research_runtime.inference.joblib.load') as loader:
            with self.assertRaisesRegex(ValueError, 'MANIFEST_HASH'):
                load_final_model(path, '0'*64, 'seven', 'logistic')
            loader.assert_not_called()
        artifact = path.parent/'final__logistic.joblib'
        original = artifact.read_bytes()
        try:
            artifact.write_bytes(original+b'changed')
            with patch('research_runtime.inference.joblib.load') as loader:
                with self.assertRaisesRegex(ValueError, 'MODEL_HASH'):
                    load_final_model(path, pin, 'seven', 'logistic')
                loader.assert_not_called()
        finally:
            artifact.write_bytes(original)

    def test_manifest_scope_and_path_rejected_before_unpickle(self):
        original_path, _ = self.manifests['seven']
        original = json.loads(original_path.read_text())
        cases = []
        m = deepcopy(original); m['software']['numpy'] = '0'; cases.append(m)
        m = deepcopy(original); m['features'].reverse(); cases.append(m)
        m = deepcopy(original); m['final_models'][0]['artifact']['file'] = '../final__logistic.joblib'; cases.append(m)
        m = deepcopy(original); m['final_models'].append(m['final_models'][0]); cases.append(m)
        m = deepcopy(original); m['final_models'][0]['recommended_research_policy'] = 'calibrated'; cases.append(m)
        m = deepcopy(original); m['training_complete'] = False; cases.append(m)
        m = deepcopy(original); m['plan_sha256'] = None; cases.append(m)
        for manifest in cases:
            path = original_path.parent/'bad_manifest.json'
            path.write_text(json.dumps(manifest), encoding='utf-8')
            with patch('research_runtime.inference.joblib.load') as loader:
                with self.assertRaises(ValueError):
                    load_final_model(path, sha(path), 'seven', 'logistic')
                loader.assert_not_called()

    def test_outer_bundle_cannot_masquerade_as_final(self):
        path, _ = self.manifests['seven']
        original = json.loads(path.read_text())
        artifact = path.parent/'final__logistic.joblib'
        original_bytes = artifact.read_bytes()
        try:
            bundle = joblib.load(artifact)
            bundle['role'] = 'NESTED_OUTER_RESEARCH_VALIDATION'
            joblib.dump(bundle, artifact)
            original['final_models'][0]['artifact']['sha256'] = sha(artifact)
            altered = path.parent/'bad_role_manifest.json'
            altered.write_text(json.dumps(original), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'BUNDLE_MISMATCH'):
                load_final_model(altered, sha(altered), 'seven', 'logistic')
        finally:
            artifact.write_bytes(original_bytes)

    def test_cli_success_and_failure_without_private_error_echo(self):
        path, pin = self.manifests['seven']
        req_path = self.root/'request.json'
        req_path.write_text(json.dumps(request()), encoding='utf-8')
        args = [sys.executable, '-m', 'research_runtime', '--manifest', str(path),
                '--manifest-sha256', pin, '--request', str(req_path)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['clinicalUse'])
        req_path.write_text('{"DO_NOT_ECHO_SECRET":NaN}', encoding='utf-8')
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('DO_NOT_ECHO_SECRET', result.stderr)


if __name__ == '__main__':
    unittest.main()
