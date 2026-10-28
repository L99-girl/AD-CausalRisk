"""Entirely constructed declaration/context pair; no data or model readers."""
from copy import deepcopy
import json

from research_runtime.input_admission import (
    SCHEMA, CONTEXT_SCHEMA, FEATURES, UNITS, mapping_digest, validate_snapshot,
)


def constructed_pair(specification='multimodal_values', family='prior_graph'):
    names = FEATURES if specification == 'multimodal_values' else FEATURES[:7]
    mapping = {name: dict(sourceId='CONSTRUCTED-SRC-'+name, dataset='CONSTRUCTED',
        table='CONSTRUCTED_TABLE', field=name, release='constructed-v1',
        language='en' if name in FEATURES[2:7] else None,
        instrumentVersion='constructed-v1' if name in FEATURES[2:7] else None,
        processingVersion='constructed-fs4.3' if name in FEATURES[8:] else None)
        for name in names}
    model = dict(family=family, specification=specification,
        role='GRAPH_FINAL' if family == 'prior_graph' else (
            'FULL_COHORT_SEVEN_VARIABLE_RESEARCH_MODEL' if specification == 'seven' else 'MULTIMODAL_FULL_COHORT_RESEARCH'),
        features=list(names), manifestSha256='a'*64, artifactSha256='b'*64,
        trainingPlanSha256='c'*64, runtimeSourceSha256='d'*64,
        softwareLockSha256='e'*64, sourceMappingSha256=mapping_digest(mapping),
        graphProtocolSha256='f'*64 if family == 'prior_graph' else None,
        predictionPolicy='raw_uncalibrated_24month_CIF')
    values = (72, 14, 26, 1.5, .5, 18, 4, 1, 3200, 3300)
    items = {name: dict(value=value, unit=UNITS[name], measuredDate='2020-01-01',
        availableDate='2020-01-02', dateBasis='MEASUREMENT_DATE',
        sourceRef=mapping[name]['sourceId'], qc='NOT_APPLICABLE' if name in FEATURES[:2] else 'PASS',
        completion='COMPLETE' if name in FEATURES[2:7] else 'NOT_APPLICABLE',
        missingReason=None, scanId='CONSTRUCTED-SCAN-1' if name in FEATURES[8:] else None,
        evidenceRef='CONSTRUCTED-EV-'+name) for name,value in zip(names, values)}
    request = dict(schemaVersion=SCHEMA, purpose='OFFLINE_RESEARCH_ADMISSION',
        dataVersion='constructed-snapshot-v1', indexDate='2020-01-02',
        predictionWindowMonths=24, availabilityPolicy='RETROSPECTIVE_SNAPSHOT',
        model=model, records=[dict(subjectCode='CONSTRUCTED-001',features=items)])
    context = dict(schemaVersion=CONTEXT_SCHEMA, dataVersion=request['dataVersion'],
        indexDate=request['indexDate'], availabilityPolicy=request['availabilityPolicy'],
        model=deepcopy(model), sourceMappings=mapping,
        evidence={item['evidenceRef']: dict(subjectCode='CONSTRUCTED-001',feature=name,
            observation=deepcopy(item)) for name,item in items.items()})
    return request, context


if __name__ == '__main__':
    request, context = constructed_pair()
    print(json.dumps(validate_snapshot(request, trusted_context=context), allow_nan=False))
