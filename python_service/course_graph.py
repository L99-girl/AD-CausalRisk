"""Versioned course prior templates and synthetic graph inspection.

The live workflow always uses the original fixed template. Candidate templates
are offline input-eligibility diagrams, never learned causal graphs or scorers.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

GRAPH_VERSION = 'synthetic-prior-v1'
TEMPLATE_SCHEMA = 'course-prior-template-v1'
PRIOR_NOTE = '研究先验约束路径，不代表已识别的个体因果效应'
NODE_SPECS = (('COGNITION', '认知状态', 'PRIOR'),
              ('WARNING', '研究型风险排序', 'MODEL'),
              ('APOE_E4_COUNT', 'APOE ε4', 'PRIOR'),
              ('MRI_HIPPOCAMPUS_L', '左海马 MRI', 'PRIOR'),
              ('MRI_HIPPOCAMPUS_R', '右海马 MRI', 'PRIOR'))
EDGE_SPECS = (('APOE_E4_COUNT', 'COGNITION'), ('MRI_HIPPOCAMPUS_L', 'COGNITION'),
              ('MRI_HIPPOCAMPUS_R', 'COGNITION'), ('COGNITION', 'WARNING'))


class GraphEvidenceError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(condition, code):
    if not condition:
        raise GraphEvidenceError(code)


def _digest(value, maximum=128 * 1024):
    digest, size = hashlib.sha256(), 0
    try:
        encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))
        for chunk in encoder.iterencode(value):
            raw = chunk.encode('utf-8')
            size += len(raw)
            _require(size <= maximum, 'GRAPH_INPUT_SIZE')
            digest.update(raw)
        return digest.hexdigest()
    except GraphEvidenceError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise GraphEvidenceError('GRAPH_JSON_INPUT') from None


def _snapshot(value, maximum=128 * 1024):
    original = _digest(value, maximum)
    try:
        owned = copy.deepcopy(value)
    except (ValueError, TypeError, RecursionError):
        raise GraphEvidenceError('GRAPH_JSON_INPUT') from None
    _require(_digest(owned, maximum) == original, 'GRAPH_INPUT_CHANGED')
    return owned


def default_graph_template():
    """Return an independently mutable JSON view of the unchanged course prior."""
    return {'schemaVersion': TEMPLATE_SCHEMA, 'mode': 'SYNTHETIC_DEMO',
            'templateVersion': GRAPH_VERSION,
            'nodes': [{'id': name, 'label': label, 'evidenceLevel': evidence}
                      for name, label, evidence in NODE_SPECS],
            'edges': [{'from': source, 'to': target, 'evidenceLevel': 'PRIOR',
                       'direction': 'CONDITIONAL', 'note': PRIOR_NOTE}
                      for source, target in EDGE_SPECS]}


def validate_default_course_graph(graph, feature_map):
    """Validate the workflow's original fixed graph before scoring any input.

    Candidate templates remain offline; this check grants no causal meaning.
    """
    _require(type(graph) is dict, 'WORKFLOW_GRAPH')
    _require(_digest(graph) == _digest(default_course_graph(feature_map)), 'WORKFLOW_GRAPH')
    return graph


def validate_graph_template(template):
    """Validate a bounded candidate without authorizing it for any scorer."""
    template = _snapshot(template, 64 * 1024)
    _require(type(template) is dict and set(template) ==
             {'schemaVersion', 'mode', 'templateVersion', 'nodes', 'edges'}, 'TEMPLATE_FIELDS')
    _require(template['schemaVersion'] == TEMPLATE_SCHEMA and template['mode'] == 'SYNTHETIC_DEMO', 'TEMPLATE_SCOPE')
    version = template['templateVersion']
    _require(type(version) is str and (version == GRAPH_VERSION or
             re.fullmatch(r'demo-[A-Za-z0-9][A-Za-z0-9-]{0,58}', version)), 'TEMPLATE_VERSION')
    nodes, edges = template['nodes'], template['edges']
    _require(type(nodes) is list and len(nodes) == 5 and type(edges) is list and len(edges) <= 4, 'TEMPLATE_SIZE')
    wanted = {name: evidence for name, _, evidence in NODE_SPECS}
    observed = set()
    for node in nodes:
        _require(type(node) is dict and set(node) == {'id', 'label', 'evidenceLevel'}, 'TEMPLATE_NODE')
        name, label = node['id'], node['label']
        _require(type(name) is str and name in wanted and name not in observed, 'TEMPLATE_NODE_ID')
        _require(type(label) is str and 0 < len(label) <= 80 and label.strip() == label, 'TEMPLATE_LABEL')
        _require(node['evidenceLevel'] == wanted[name], 'TEMPLATE_EVIDENCE')
        observed.add(name)
    seen = set()
    for edge in edges:
        _require(type(edge) is dict and set(edge) == {'from', 'to', 'evidenceLevel', 'direction', 'note'}, 'TEMPLATE_EDGE')
        source, target = edge['from'], edge['to']
        _require(type(source) is str and type(target) is str and (source, target) in EDGE_SPECS,
                 'TEMPLATE_DIRECTION')
        _require((source, target) not in seen, 'TEMPLATE_DUPLICATE_EDGE')
        _require(edge['evidenceLevel'] == 'PRIOR' and edge['direction'] == 'CONDITIONAL'
                 and edge['note'] == PRIOR_NOTE, 'TEMPLATE_EVIDENCE')
        seen.add((source, target))
    # The allowlist is a DAG: feature -> cognition -> warning. A self-loop,
    # reverse edge, dangling node or other cycle cannot pass this policy.
    if version == GRAPH_VERSION:
        _require(template == default_graph_template(), 'DEFAULT_TEMPLATE_IMMUTABLE')
    return template


def _render_graph(feature_map, template):
    nodes = []
    for spec in template['nodes']:
        name = spec['id']
        active = name in ('COGNITION', 'WARNING') or name in feature_map
        node = {'id': name, 'label': spec['label'], 'status': 'ACTIVE' if active else 'MISSING',
                'evidenceLevel': spec['evidenceLevel']}
        if name not in ('COGNITION', 'WARNING'):
            node['observedAt'] = feature_map.get(name, {}).get('recordedAt')
        nodes.append(node)
    edges = [{'from': spec['from'], 'to': spec['to'],
              'status': 'ACTIVE' if spec['from'] == 'COGNITION' or spec['from'] in feature_map else 'MISSING',
              'evidenceLevel': spec['evidenceLevel'], 'direction': spec['direction'], 'note': spec['note']}
             for spec in template['edges']]
    paths = [{'nodes': [edge['from'], edge['to']], 'status': edge['status'],
              'evidenceLevel': edge['evidenceLevel']} for edge in edges]
    return {'nodes': nodes, 'edges': edges, 'paths': paths, 'graphVersion': template['templateVersion']}


def default_course_graph(feature_map):
    """Internal already-qualified selection -> exactly the original wire graph."""
    return _render_graph(feature_map, default_graph_template())


def _owned_request(request):
    from .deepagent_contract import request_snapshot
    return request_snapshot(_snapshot(request))


def inspect_course_graph(request, *, template=None):
    """Inspect a declared prior with original DEMO selection; never score it."""
    from .course_fusion import select_fusion
    from .deepagent_contract import payload_digest
    request = _owned_request(request)
    template = validate_graph_template(default_graph_template() if template is None else template)
    selected = select_fusion(request)
    blocked = selected['blocked']
    original = template == default_graph_template()
    graph = {'nodes': [], 'edges': [], 'paths': []} if blocked else _render_graph(selected['features'], template)
    return {'scope': 'COURSE_SYNTHETIC_PRIOR_INSPECTION', 'subjectCode': request['subjectCode'],
            'runId': request['runId'], 'dataVersion': request['dataVersion'],
            'requestModelVersion': request['modelVersion'], 'requestSha256': payload_digest(request),
            'template': template, 'templateSha256': _digest(template, 64 * 1024),
            'indexDate': selected['indexDate'], 'blockingReasons': list(selected['blockingReasons']),
            'qualityBlocked': blocked, 'graph': graph,
            'usesOriginalTemplate': original, 'candidateTemplate': not original,
            'originalScoringEligible': original and not blocked,
            'configuredCandidateUsedByScorer': False, 'modelExecuted': False, 'modelFitted': False,
            'predictionProduced': False, 'riskScore': None, 'persisted': False,
            'sourceAuthenticityVerified': False, 'historicalAvailabilityVerified': False,
            'edgeStabilityEstablished': False, 'causalEffectsIdentified': False,
            'clinicalValidityAssessed': False}
