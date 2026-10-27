"""Versioned, in-memory declaration checks; no readers, models or prediction.

The caller supplies an independently controlled context. Agreement with that
context does not establish its authenticity, data access rights or clinical use.
Only constructed inputs have been accepted in this implementation stage.
"""
from collections import Counter
from copy import deepcopy
from datetime import date
import hashlib
import json
import math
import re


SCHEMA = 'research-real-input-admission-v1'
CONTEXT_SCHEMA = 'research-input-context-v1'
RESULT_SCHEMA = 'research-input-admission-result-v1'
FEATURES = ('age_years', 'education_years', 'mmse', 'cdr_sb', 'cdr_global',
            'adas__total13', 'faq__faqtotal', 'apoe4_count',
            'mri_left_hippocampus_volume', 'mri_right_hippocampus_volume')
UNITS = dict(zip(FEATURES, ('years', 'years', 'score', 'score', 'score',
                          'score', 'score', 'count', 'mm3', 'mm3')))
SPECS = {'seven': FEATURES[:7], 'multimodal_values': FEATURES}
SHA = re.compile(r'[0-9a-f]{64}\Z')
TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z')
ITEM_KEYS = {'value', 'unit', 'measuredDate', 'availableDate', 'dateBasis',
             'sourceRef', 'qc', 'completion', 'missingReason', 'scanId', 'evidenceRef'}
SOURCE_KEYS = {'sourceId', 'dataset', 'table', 'field', 'release',
               'language', 'instrumentVersion', 'processingVersion'}
MODEL_KEYS = {'family', 'specification', 'role', 'features', 'manifestSha256',
              'artifactSha256', 'trainingPlanSha256', 'runtimeSourceSha256',
              'softwareLockSha256', 'sourceMappingSha256', 'graphProtocolSha256',
              'predictionPolicy'}
POLICY = {'version': SCHEMA, 'windowMonths': 24, 'maximumRecords': 100,
          'maximumJSONBytes': 131072, 'MRIWindowDays': 365,
          'availabilityPolicies': ['RETROSPECTIVE_SNAPSHOT', 'AS_OF_INDEX'],
          'predictionPolicy': 'raw_uncalibrated_24month_CIF',
          'missingReasons': ['UNKNOWN', 'NOT_COLLECTED', 'UNAVAILABLE', 'QC_FAILED']}


class AdmissionError(ValueError):
    """A stable code without subject identifiers, source text or input values."""


def _fail(code):
    raise AdmissionError(code) from None


def _keys(value, keys, code):
    if type(value) is not dict or set(value) != keys:
        _fail(code)


def _token(value):
    return type(value) is str and TOKEN.fullmatch(value) is not None


def _sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def _date(value):
    if type(value) is not str or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value) is None:
        _fail('DATE_FORMAT')
    try:
        return date.fromisoformat(value)
    except ValueError:
        _fail('DATE_FORMAT')


def mapping_digest(mapping):
    """Digest a nonclinical field mapping; never derive per-person hashes."""
    try:
        raw = json.dumps(mapping, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        _fail('SOURCE_MAPPING_FORMAT')
    return hashlib.sha256(raw).hexdigest()


def _snapshot(value, code):
    # Freeze caller input and bound complexity without relying on object identity.
    # Unsupported Python objects are rejected before they can define comparison.
    if type(value) is not dict:
        _fail(code)
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        _fail(code)
    limit = 1048576 if code == 'CONTEXT_FORMAT' else POLICY['maximumJSONBytes']
    if len(raw) > limit:
        _fail('CONTEXT_TOO_LARGE' if code == 'CONTEXT_FORMAT' else 'REQUEST_TOO_LARGE')
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        _fail(code)


def _model(model):
    _keys(model, MODEL_KEYS, 'MODEL_IDENTITY_FIELDS')
    spec, family = model['specification'], model['family']
    if type(spec) is not str or spec not in SPECS or type(family) is not str:
        _fail('MODEL_SPECIFICATION')
    if model['features'] != list(SPECS[spec]):
        _fail('MODEL_FEATURE_ORDER')
    if family == 'prior_graph':
        if spec != 'multimodal_values' or model['role'] != 'GRAPH_FINAL' or not _sha(model['graphProtocolSha256']):
            _fail('FINAL_GRAPH_MODEL_REQUIRED')
    elif family in ('logistic', 'random_forest', 'xgboost'):
        role = 'FULL_COHORT_SEVEN_VARIABLE_RESEARCH_MODEL' if spec == 'seven' else 'MULTIMODAL_FULL_COHORT_RESEARCH'
        if model['role'] != role or model['graphProtocolSha256'] is not None:
            _fail('FINAL_TABLE_MODEL_REQUIRED')
    else:
        _fail('MODEL_FAMILY')
    if any(not _sha(model[k]) for k in MODEL_KEYS if k.endswith('Sha256') and k != 'graphProtocolSha256'):
        _fail('MODEL_IDENTITY_HASH')
    if model['predictionPolicy'] != POLICY['predictionPolicy']:
        _fail('RAW_24_MONTH_POLICY_REQUIRED')


def _item(item, name):
    _keys(item, ITEM_KEYS, 'FEATURE_METADATA_FIELDS')
    if item['unit'] != UNITS[name]:
        _fail('FEATURE_UNIT')
    if item['qc'] not in ('PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE') or item['completion'] not in ('COMPLETE', 'INCOMPLETE', 'UNKNOWN', 'NOT_APPLICABLE'):
        _fail('QUALITY_ENUM')
    if item['dateBasis'] not in ('MEASUREMENT_DATE', 'REGISTRY_PROXY', 'DERIVED_AT_INDEX', 'UNKNOWN'):
        _fail('DATE_BASIS_ENUM')
    for key in ('sourceRef', 'scanId', 'evidenceRef'):
        if item[key] is not None and not _token(item[key]):
            _fail('PROVENANCE_REFERENCE_FORMAT')
    if name not in FEATURES[8:] and item['scanId'] is not None:
        _fail('SCAN_ID_ONLY_FOR_MRI')
    value = item['value']
    if value is None:
        if (item['measuredDate'] is not None or item['availableDate'] is not None
                or item['dateBasis'] != 'UNKNOWN' or item['scanId'] is not None):
            _fail('MISSING_VALUE_DATES_OR_SCAN')
        if item['missingReason'] not in POLICY['missingReasons']:
            _fail('MISSING_REASON_REQUIRED')
        if item['qc'] == 'PASS' or item['completion'] == 'COMPLETE':
            _fail('MISSING_VALUE_COMPLETION_CONFLICT')
        if (item['missingReason'] == 'QC_FAILED') != (item['qc'] == 'FAIL'):
            _fail('MISSING_QC_REASON_CONFLICT')
        return
    if type(value) not in (int, float):
        _fail('FINITE_NUMBER_OR_NULL')
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        _fail('FINITE_NUMBER_OR_NULL')
    if item['missingReason'] is not None:
        _fail('OBSERVED_VALUE_MISSING_REASON')
    if name == 'apoe4_count' and (type(value) is not int or value not in (0, 1, 2)):
        _fail('APOE_INTEGER_COUNT')
    if name in FEATURES[8:] and value <= 0:
        _fail('POSITIVE_MRI_MM3')
    if item['measuredDate'] is not None:
        _date(item['measuredDate'])
    if item['availableDate'] is not None:
        _date(item['availableDate'])


def _context(context):
    _keys(context, {'schemaVersion', 'dataVersion', 'indexDate', 'availabilityPolicy',
                    'model', 'sourceMappings', 'evidence'}, 'CONTEXT_FIELDS')
    if context['schemaVersion'] != CONTEXT_SCHEMA or not _token(context['dataVersion']):
        _fail('CONTEXT_VERSION')
    _date(context['indexDate'])
    if context['availabilityPolicy'] not in POLICY['availabilityPolicies']:
        _fail('CONTEXT_AVAILABILITY_POLICY')
    _model(context['model'])
    features = SPECS[context['model']['specification']]
    mapping = context['sourceMappings']
    _keys(mapping, set(features), 'SOURCE_MAPPING_FEATURES')
    ids = set()
    for name, row in mapping.items():
        _keys(row, SOURCE_KEYS, 'SOURCE_MAPPING_FIELDS')
        if not _token(row['sourceId']) or row['sourceId'] in ids:
            _fail('SOURCE_MAPPING_ID')
        ids.add(row['sourceId'])
        if any(row[k] is not None and not _token(row[k]) for k in SOURCE_KEYS):
            _fail('SOURCE_MAPPING_VALUE')
    if mapping_digest(mapping) != context['model']['sourceMappingSha256']:
        _fail('CONTEXT_MAPPING_HASH')
    evidence = context['evidence']
    if type(evidence) is not dict or len(evidence) > 1000:
        _fail('EVIDENCE_CATALOG')
    for ref, row in evidence.items():
        if not _token(ref):
            _fail('EVIDENCE_REFERENCE')
        _keys(row, {'subjectCode', 'feature', 'observation'}, 'EVIDENCE_FIELDS')
        if not _token(row['subjectCode']) or type(row['feature']) is not str or row['feature'] not in features:
            _fail('EVIDENCE_SCOPE')
        _item(row['observation'], row['feature'])
        if row['observation']['evidenceRef'] != ref:
            _fail('EVIDENCE_SELF_REFERENCE')


def validate_snapshot(request, *, trusted_context):
    """Return aggregate consistency diagnostics; never return rows or predictions.

    Do not construct ``trusted_context`` by copying the incoming request. Its
    model identity, mappings and row evidence must be controlled independently.
    This function checks agreement, not that external independence/authenticity.
    """
    request = _snapshot(request, 'REQUEST_FORMAT')
    context = _snapshot(trusted_context, 'CONTEXT_FORMAT')
    _context(context)
    _keys(request, {'schemaVersion', 'purpose', 'dataVersion', 'indexDate',
                    'predictionWindowMonths', 'availabilityPolicy', 'model', 'records'}, 'REQUEST_FIELDS')
    if request['schemaVersion'] != SCHEMA or request['purpose'] != 'OFFLINE_RESEARCH_ADMISSION':
        _fail('REQUEST_VERSION_OR_PURPOSE')
    if not _token(request['dataVersion']):
        _fail('DATA_VERSION_FORMAT')
    if type(request['predictionWindowMonths']) is not int or request['predictionWindowMonths'] != 24:
        _fail('ONLY_24_MONTH_WINDOW')
    policy = request['availabilityPolicy']
    if policy not in POLICY['availabilityPolicies']:
        _fail('AVAILABILITY_POLICY')
    index = _date(request['indexDate'])
    _model(request['model'])
    records = request['records']
    if type(records) is not list or not 1 <= len(records) <= 100:
        _fail('RECORD_COUNT')
    expected = SPECS[context['model']['specification']]
    counts = Counter(); missing = Counter(); blocked = set(); seen = set()

    def issue(code, severity, feature, position):
        counts[code, severity, feature] += 1
        if severity == 'BLOCK':
            blocked.add(position)

    if (request['model'] != context['model'] or request['dataVersion'] != context['dataVersion']
            or request['indexDate'] != context['indexDate'] or policy != context['availabilityPolicy']):
        issue('REQUEST_CONTEXT_BINDING_MISMATCH', 'BLOCK', None, -1)
    for position, record in enumerate(records):
        _keys(record, {'subjectCode', 'features'}, 'RECORD_FIELDS')
        sid = record['subjectCode']
        if not _token(sid) or sid in seen:
            _fail('UNIQUE_SUBJECT_CODE_REQUIRED')
        seen.add(sid)
        _keys(record['features'], set(expected), 'EXACT_FEATURE_SET')
        features = record['features']
        if all(features[n].get('value') is None for n in expected[:7] if type(features[n]) is dict):
            issue('NO_CORE_INPUT', 'BLOCK', None, position)
        for name, item in features.items():
            _item(item, name)
            source = context['sourceMappings'][name]
            ref = item['evidenceRef']
            if ref is not None:
                bound = context['evidence'].get(ref)
                if bound != {'subjectCode': sid, 'feature': name, 'observation': item}:
                    issue('RECORD_EVIDENCE_MISMATCH', 'BLOCK', name, position)
            if item['value'] is None:
                missing[name] += 1
                if ref is None:
                    issue('MISSING_EVIDENCE_UNKNOWN', 'BLOCK', name, position)
                if item['sourceRef'] is not None and item['sourceRef'] != source['sourceId']:
                    issue('SOURCE_MAPPING_MISMATCH', 'BLOCK', name, position)
                continue
            if ref is None:
                issue('RECORD_EVIDENCE_UNKNOWN', 'BLOCK', name, position)
            if item['sourceRef'] != source['sourceId']:
                issue('SOURCE_MAPPING_MISMATCH', 'BLOCK', name, position)
            required = ['dataset', 'table', 'field', 'release']
            if name in FEATURES[2:7]:
                required += ['language', 'instrumentVersion']
            if name in FEATURES[8:]:
                required += ['processingVersion']
            if any(source[k] is None for k in required):
                issue('SOURCE_METADATA_UNKNOWN', 'BLOCK', name, position)
            expected_qc = 'NOT_APPLICABLE' if name in FEATURES[:2] else 'PASS'
            expected_completion = 'COMPLETE' if name in FEATURES[2:7] else 'NOT_APPLICABLE'
            if item['qc'] != expected_qc:
                issue('QC_' + item['qc'], 'BLOCK', name, position)
            if item['completion'] != expected_completion:
                issue('COMPLETION_' + item['completion'], 'BLOCK', name, position)
            measured = _date(item['measuredDate']) if item['measuredDate'] is not None else None
            available = _date(item['availableDate']) if item['availableDate'] is not None else None
            if measured is None or item['dateBasis'] == 'UNKNOWN':
                issue('MEASUREMENT_DATE_UNKNOWN', 'BLOCK', name, position)
            elif measured > index:
                issue('POST_INDEX_MEASUREMENT', 'BLOCK', name, position)
            if available is not None and measured is not None and available < measured:
                issue('SOURCE_DATE_ORDER', 'BLOCK', name, position)
            if item['dateBasis'] == 'REGISTRY_PROXY':
                issue('REGISTRY_DATE_PROXY', 'BLOCK' if policy == 'AS_OF_INDEX' else 'WARN', name, position)
            if item['dateBasis'] == 'DERIVED_AT_INDEX' and (name != 'age_years' or measured != index):
                issue('DERIVED_DATE_SCOPE', 'BLOCK', name, position)
            if available is None:
                issue('AVAILABILITY_UNKNOWN', 'BLOCK' if policy == 'AS_OF_INDEX' else 'WARN', name, position)
            elif available > index:
                issue('POST_INDEX_AVAILABILITY', 'BLOCK' if policy == 'AS_OF_INDEX' else 'WARN', name, position)
        if len(expected) == 10:
            left, right = (features[n] for n in FEATURES[8:])
            if (left['value'] is None) != (right['value'] is None):
                issue('BILATERAL_MRI_PAIR_REQUIRED', 'BLOCK', None, position)
            elif left['value'] is not None:
                keys = ('scanId', 'measuredDate', 'availableDate', 'dateBasis')
                ls, rs = (context['sourceMappings'][n] for n in FEATURES[8:])
                if (left['scanId'] is None or any(left[k] != right[k] for k in keys)
                        or any(ls[k] != rs[k] for k in ('dataset', 'table', 'release', 'processingVersion'))):
                    issue('SAME_SCAN_AND_PROCESSING_REQUIRED', 'BLOCK', None, position)
                if left['measuredDate'] is not None and (index - _date(left['measuredDate'])).days > 365:
                    issue('MRI_OUTSIDE_365_DAYS', 'BLOCK', None, position)
    blocked_count = len(records) if -1 in blocked else len(blocked)
    issues = [dict(code=code, severity=severity, feature=feature, count=count)
              for (code, severity, feature), count in sorted(counts.items(), key=lambda x: (x[0][0], x[0][2] or ''))]
    return dict(schemaVersion=RESULT_SCHEMA, status='BLOCKED' if blocked_count else 'METADATA_CONSISTENT',
                recordCount=len(records), blockedRecordCount=blocked_count,
                featureOrder=list(expected), missingFeatureCounts={n: missing[n] for n in expected},
                availabilityPolicy=policy, model=deepcopy(context['model']), issues=issues,
                predictionAllowed=False, clinicalUse=False, sourceAuthenticityCertified=False,
                historicalAvailabilityCertified=False, individualCausalEffectIdentified=False)


def validate_json(raw, *, trusted_context):
    """Decode caller-supplied bytes, rejecting duplicate keys and non-JSON numbers."""
    if type(raw) is not bytes or len(raw) > POLICY['maximumJSONBytes']:
        _fail('JSON_BYTES_OR_SIZE')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail('DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def constant(_):
        _fail('NONFINITE_JSON')
    try:
        request = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except AdmissionError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        _fail('JSON_FORMAT')
    return validate_snapshot(request, trusted_context=trusted_context)
