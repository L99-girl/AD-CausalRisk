"""Pinned final-model loading and synthetic offline acceptance.

This is a Python-owned local file format, not a Java/HTTP contract. A caller
must independently trust the manifest and provide its SHA256. Joblib artifacts
are executable pickle data; hashes bind bytes, not the trustworthiness of code.
"""
from __future__ import annotations

from datetime import date
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import re
import tempfile

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .discrete import predict_cif
from .estimators import BASE, ADDED, FAMILIES, SPECS, information_arm

SCHEMA = 'research-model-smoke-v1'
RUNTIME_DEPENDENCIES = ('numpy', 'pandas', 'scikit-learn', 'scipy', 'joblib', 'threadpoolctl', 'xgboost')
UNITS = dict(zip(BASE + ADDED, ('years', 'years', 'score', 'score', 'score', 'score', 'score',
                              'count', 'mm3', 'mm3')))
ROLES = {'seven': 'FULL_COHORT_SEVEN_VARIABLE_RESEARCH_MODEL',
         'modality_availability': 'MULTIMODAL_FULL_COHORT_RESEARCH',
         'multimodal_values': 'MULTIMODAL_FULL_COHORT_RESEARCH'}
SHA256 = re.compile(r'[0-9a-f]{64}\Z')


def _reject_constant(_):
    raise ValueError('NONFINITE_JSON')


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def read_json_bytes(raw, limit=131072):
    if len(raw) > limit:
        raise ValueError('JSON_TOO_LARGE')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('DATE_FORMAT')
    return date.fromisoformat(value)


def validate_request(request):
    """Accept only explicit synthetic snapshots, before deserializing anything."""
    if not isinstance(request, dict) or set(request) != {
            'schemaVersion', 'purpose', 'specification', 'family', 'dataVersion',
            'indexDate', 'predictionWindowMonths', 'records'}:
        raise ValueError('REQUEST_FIELDS')
    if request['schemaVersion'] != SCHEMA or request['purpose'] != 'SYNTHETIC_ACCEPTANCE':
        raise ValueError('SYNTHETIC_ACCEPTANCE_ONLY')
    spec, family = request['specification'], request['family']
    if not isinstance(spec, str) or spec not in SPECS or not isinstance(family, str) or family not in FAMILIES:
        raise ValueError('UNKNOWN_MODEL_SPECIFICATION')
    if type(request['predictionWindowMonths']) is not int or request['predictionWindowMonths'] != 24:
        raise ValueError('ONLY_24_MONTH_CIF')
    if not isinstance(request['dataVersion'], str) or not re.fullmatch(r'synthetic-[A-Za-z0-9_.-]{1,80}', request['dataVersion']):
        raise ValueError('SYNTHETIC_DATA_VERSION_REQUIRED')
    index = _date(request['indexDate'])
    records = request['records']
    if not isinstance(records, list) or not 1 <= len(records) <= 100:
        raise ValueError('RECORD_COUNT')
    rows, sources, identifiers = [], [], set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {'subjectCode', 'features'}:
            raise ValueError('RECORD_FIELDS')
        sid = record['subjectCode']
        if not isinstance(sid, str) or not re.fullmatch(r'SYNTHETIC-[A-Za-z0-9_-]{1,60}', sid) or sid in identifiers:
            raise ValueError('UNIQUE_SYNTHETIC_ID_REQUIRED')
        identifiers.add(sid)
        features = record['features']
        if not isinstance(features, dict) or set(features) != set(SPECS[spec]):
            raise ValueError('EXACT_FEATURE_SET_REQUIRED')
        row, trace = {'subject_id': sid}, {}
        for name, item in features.items():
            if not isinstance(item, dict) or set(item) != {'value', 'unit', 'measuredDate', 'availableDate', 'source', 'qc'}:
                raise ValueError('FEATURE_METADATA_REQUIRED')
            value = item['value']
            if item['unit'] != UNITS[name] or item['source'] != 'SYNTHETIC' or item['qc'] != 'SYNTHETIC':
                raise ValueError('FEATURE_UNIT_OR_SYNTHETIC_SOURCE')
            if value is not None:
                if type(value) not in (int, float):
                    raise ValueError('FINITE_NUMBER_OR_NULL_REQUIRED')
                try:
                    finite = math.isfinite(value)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ValueError('FINITE_NUMBER_OR_NULL_REQUIRED')
                if name == 'apoe4_count' and (type(value) is not int or value not in (0, 1, 2)):
                    raise ValueError('APOE_INTEGER_COUNT')
                if name in ADDED[1:] and value <= 0:
                    raise ValueError('POSITIVE_MRI_MM3_REQUIRED')
                measured = _date(item['measuredDate'])
                available = _date(item['availableDate']) if item['availableDate'] is not None else None
                if measured > index or (available is not None and available < measured):
                    raise ValueError('SOURCE_DATE_ORDER')
            elif item['measuredDate'] is not None or item['availableDate'] is not None:
                raise ValueError('MISSING_VALUE_REQUIRES_NULL_DATES')
            row[name] = np.nan if value is None else value
            trace[name] = dict(item)
        if all(pd.isna(row[name]) for name in BASE):
            raise ValueError('NO_CORE_INPUT')
        if spec != 'seven':
            left, right = ADDED[1:]
            if pd.isna(row[left]) != pd.isna(row[right]):
                raise ValueError('BILATERAL_MRI_PAIR_REQUIRED')
            if not pd.isna(row[left]):
                if (trace[left]['measuredDate'] != trace[right]['measuredDate']
                        or trace[left]['availableDate'] != trace[right]['availableDate']
                        or (index - _date(trace[left]['measuredDate'])).days > 365):
                    raise ValueError('SAME_SCAN_WITHIN_365_DAYS_REQUIRED')
        rows.append(row)
        sources.append({'subjectCode': sid, 'features': trace})
    return information_arm(pd.DataFrame(rows), spec), sources


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load_final_model(manifest_path, trusted_manifest_sha256, specification, family):
    """Load only a pinned final model from the manifest's own directory.

    No automatic family selection, calibration, downloads, fit or retry. The
    exact artifact bytes that were hashed are passed to joblib, avoiding a
    second path read between verification and deserialization.
    """
    if specification not in SPECS or family not in FAMILIES:
        raise ValueError('UNKNOWN_MODEL_SPECIFICATION')
    if not isinstance(trusted_manifest_sha256, str) or not SHA256.fullmatch(trusted_manifest_sha256):
        raise ValueError('TRUSTED_MANIFEST_SHA256_REQUIRED')
    path = Path(manifest_path).resolve(strict=True)
    with path.open('rb') as stream:
        raw = stream.read(1048577)
    if len(raw) > 1048576 or _digest(raw) != trusted_manifest_sha256:
        raise ValueError('MANIFEST_HASH_MISMATCH')
    manifest = read_json_bytes(raw, 1048576)
    if manifest.get('features') != list(SPECS[specification]):
        raise ValueError('MANIFEST_FEATURES_MISMATCH')
    plan = manifest.get('plan_sha256')
    if not isinstance(plan, str) or not SHA256.fullmatch(plan):
        raise ValueError('MANIFEST_PLAN_MISSING')
    for name in RUNTIME_DEPENDENCIES:
        if manifest.get('software', {}).get(name) != version(name):
            raise ValueError('MODEL_SOFTWARE_MISMATCH')
    if specification == 'seven':
        if manifest.get('training_complete') is not True:
            raise ValueError('TRAINING_NOT_COMPLETE')
        matches = [m for m in manifest['final_models'] if m['family'] == family]
        if len(matches) != 1 or matches[0].get('recommended_research_policy') != 'raw':
            raise ValueError('FINAL_RAW_MODEL_REQUIRED')
        artifact = matches[0]['artifact']
        filename = f'final__{family}.joblib'
    else:
        if any(manifest.get(key) is not False for key in ('clinical_use', 'default_model_changed', 'calibrated')):
            raise ValueError('MULTIMODAL_BOUNDARY_MISMATCH')
        matches = [m for m in manifest['models'] if m['family'] == family and m['arm'] == specification
                   and m['role'] == ROLES[specification]]
        if len(matches) != 1:
            raise ValueError('UNIQUE_FINAL_MODEL_REQUIRED')
        artifact = matches[0]
        filename = f'final__{family}__{specification}.joblib'
    if artifact['file'] != filename or not SHA256.fullmatch(artifact['sha256']):
        raise ValueError('FINAL_MODEL_FILENAME_OR_HASH')
    model_path = path.parent / filename
    if model_path.is_symlink() or model_path.resolve(strict=True).parent != path.parent:
        raise ValueError('MODEL_PATH_OUTSIDE_MANIFEST_DIRECTORY')
    with model_path.open('rb') as source, tempfile.SpooledTemporaryFile(max_size=8*1024*1024) as snapshot:
        digest = hashlib.sha256()
        total = 0
        while chunk := source.read(1024*1024):
            total += len(chunk)
            if total > 512*1024*1024:
                raise ValueError('MODEL_TOO_LARGE')
            digest.update(chunk)
            snapshot.write(chunk)
        if digest.hexdigest() != artifact['sha256']:
            raise ValueError('MODEL_HASH_MISMATCH')
        snapshot.seek(0)
        bundle = joblib.load(snapshot)
    if (not isinstance(bundle, dict) or bundle.get('role') != ROLES[specification]
            or bundle.get('family') != family or bundle.get('columns') != list(SPECS[specification])
            or bundle.get('clinical_use') is not False
            or bundle.get('training_plan_sha256' if specification == 'seven' else 'plan_sha256') != plan):
        raise ValueError('MODEL_BUNDLE_MISMATCH')
    if specification == 'seven':
        if bundle.get('recommended_research_policy') != 'raw' or bundle.get('exact_asof_certified') is not False:
            raise ValueError('RAW_RESEARCH_POLICY_REQUIRED')
    elif (bundle.get('arm') != specification or bundle.get('retrospective_only') is not True
          or bundle.get('prediction_policy') != 'raw_uncalibrated_24month_CIF'):
        raise ValueError('MULTIMODAL_POLICY_MISMATCH')
    model = bundle['model']
    if list(model.named_steps) != ['preprocess', 'hazards'] or not np.array_equal(
            np.sort(model.named_steps['hazards'].classes_), [0, 1, 2]):
        raise ValueError('THREE_CAUSE_PIPELINE_REQUIRED')
    return bundle, {'manifestSha256': trusted_manifest_sha256, 'artifactSha256': artifact['sha256'],
                    'trainingPlanSha256': plan, 'artifact': filename}


def run_acceptance(request, manifest_path, trusted_manifest_sha256):
    # Snapshot also rejects non-JSON values. Validate before any model read.
    raw = json.dumps(request, allow_nan=False, ensure_ascii=False).encode('utf-8')
    request = read_json_bytes(raw)
    frame, sources = validate_request(request)
    spec, family = request['specification'], request['family']
    bundle, identity = load_final_model(manifest_path, trusted_manifest_sha256, spec, family)
    with threadpool_limits(limits=1):
        result = predict_cif(bundle['model'], frame, list(SPECS[spec]))
    values = result[['ad_cif_24m', 'other_dementia_cif_24m']].to_numpy(float)
    if not np.isfinite(values).all() or (values < 0).any() or (values > 1).any() or (values.sum(axis=1) > 1+1e-12).any():
        raise ValueError('INVALID_CIF')
    return {'schemaVersion': SCHEMA, 'purpose': 'SYNTHETIC_ACCEPTANCE',
            'specification': spec, 'family': family, 'dataVersion': request['dataVersion'],
            'indexDate': request['indexDate'], 'predictionWindowMonths': 24,
            'predictionPolicy': 'raw', 'clinicalUse': False, 'historicalAvailabilityCertified': False,
            'defaultModelChanged': False, 'requestSha256': _digest(raw), 'model': identity,
            'sources': sources, 'predictions': result.to_dict(orient='records'),
            'limitations': ['Synthetic input checks engineering compatibility only.',
                            'These CIFs are not clinically validated personal probabilities.',
                            'No causal effect, source authenticity or historical availability is certified.',
                            'Java business integration and real-input release require separate acceptance.']}
