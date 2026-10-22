"""Fixed template compatibility and bounded candidate-only prior inspection."""
import copy
import hashlib
import itertools
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from python_service.course_graph import (
    GraphEvidenceError, default_graph_template, validate_graph_template, inspect_course_graph,
)
from python_service.deepagent_contract import run_workflow, AgentContractError
from python_service.demo_scoring import score_java_synthetic_payload

ROOT = Path(__file__).resolve().parents[1]


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


def candidate():
    value = default_graph_template()
    value['templateVersion'] = 'demo-prior-candidate-1'
    return value


class GraphTemplateTests(unittest.TestCase):
    def test_default_template_returns_detached_content_and_canonical_hash(self):
        a = default_graph_template()
        a['nodes'][0]['label'] = 'edited'
        b = default_graph_template()
        self.assertNotEqual(a, b)
        inspection = inspect_course_graph(request())
        encoded = json.dumps(b, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        self.assertEqual(inspection['templateSha256'], hashlib.sha256(encoded).hexdigest())
        self.assertEqual(validate_graph_template(b), b)

    def test_100_shipped_graphs_match_original_workflow(self):
        bodies = json.loads((ROOT / 'fixtures/synthetic_subjects_100.json').read_text(encoding='utf-8'))['subjects']
        for body in bodies:
            self.assertEqual(inspect_course_graph(body)['graph'], run_workflow(body, score_java_synthetic_payload)['graph'])

    def test_64_missing_combinations_and_quality_gates(self):
        for cognition, features in itertools.product(range(8), repeat=2):
            body = request()
            for bit, key in enumerate(('mmse', 'moca', 'cdrSb')):
                if cognition & (1 << bit):
                    body['visits'][-1][key] = None
            body['features'] = [row for bit, row in enumerate(body['features']) if not features & (1 << bit)]
            value = inspect_course_graph(body)
            original = run_workflow(body, score_java_synthetic_payload)
            self.assertEqual(value['graph'], original['graph'])
            self.assertEqual(value['qualityBlocked'], original['status'] == 'BLOCKED')

    def test_candidate_labels_edges_and_version_do_not_change_live_scoring(self):
        body = request()
        before = run_workflow(body, score_java_synthetic_payload)
        template = candidate()
        template['nodes'][0]['label'] = '候选认知节点'
        template['edges'].clear()
        result = inspect_course_graph(body, template=template)
        self.assertEqual(result['graph']['edges'], [])
        self.assertTrue(result['candidateTemplate'])
        self.assertFalse(result['originalScoringEligible'])
        self.assertFalse(result['configuredCandidateUsedByScorer'])
        self.assertIsNone(result['riskScore'])
        after = run_workflow(body, score_java_synthetic_payload)
        self.assertEqual(before['graph'], after['graph'])
        self.assertEqual(before['riskScore'], after['riskScore'])

    def test_original_version_cannot_label_edited_content(self):
        for edit in ('label', 'edges', 'order'):
            value = default_graph_template()
            if edit == 'label':
                value['nodes'][0]['label'] = 'edited'
            elif edit == 'edges':
                value['edges'].pop()
            else:
                value['nodes'].reverse()
            with self.subTest(edit=edit), self.assertRaisesRegex(GraphEvidenceError, 'DEFAULT_TEMPLATE_IMMUTABLE'):
                validate_graph_template(value)

    def test_duplicate_node_dangling_node_and_unknown_node_rejected(self):
        for node_id in ('COGNITION', 'MISSING', 'AGE'):
            value = candidate()
            value['nodes'][-1]['id'] = node_id
            with self.assertRaisesRegex(GraphEvidenceError, 'TEMPLATE_NODE_ID'):
                validate_graph_template(value)

    def test_reversed_self_loop_unknown_and_cyclic_edges_rejected(self):
        for source, target in (('COGNITION', 'APOE_E4_COUNT'), ('WARNING', 'WARNING'),
                               ('NOT_A_NODE', 'COGNITION'), ('WARNING', 'COGNITION')):
            value = candidate()
            value['edges'][0].update({'from': source, 'to': target})
            with self.assertRaisesRegex(GraphEvidenceError, 'TEMPLATE_DIRECTION'):
                validate_graph_template(value)

    def test_duplicate_edge_rejected(self):
        value = candidate()
        value['edges'][0] = dict(value['edges'][1])
        with self.assertRaisesRegex(GraphEvidenceError, 'TEMPLATE_DUPLICATE_EDGE'):
            validate_graph_template(value)

    def test_extra_weights_learned_evidence_and_asserted_causality_rejected(self):
        for field, content in (('weight', .9), ('evidenceLevel', 'LEARNED'),
                               ('direction', 'CAUSAL'), ('note', 'causal effect established')):
            value = candidate()
            value['edges'][0][field] = content
            with self.assertRaises(GraphEvidenceError):
                validate_graph_template(value)

    def test_scope_version_and_unknown_fields_rejected(self):
        for field, content in (('mode', 'REAL'), ('templateVersion', 'v1'),
                               ('schemaVersion', 'unknown'), ('extra', True)):
            value = candidate()
            value[field] = content
            with self.assertRaises(GraphEvidenceError):
                validate_graph_template(value)

    def test_invalid_labels_unicode_nonfinite_and_size_rejected(self):
        for label in ('', ' trailing ', 'x' * 81, '\ud800', float('nan'), 'x' * 65536):
            value = candidate()
            value['nodes'][0]['label'] = label
            with self.assertRaises(GraphEvidenceError):
                validate_graph_template(value)

    def test_invalid_template_shapes_fail_cleanly(self):
        for value in (None, [], {}, {'nodes': True}):
            with self.assertRaises(GraphEvidenceError):
                validate_graph_template(value)

    def test_no_scorer_called_and_inputs_outputs_detached(self):
        body, template = request(), candidate()
        before = copy.deepcopy([body, template])
        with patch('python_service.demo_scoring.score_java_synthetic_payload', side_effect=AssertionError('no score')):
            value = inspect_course_graph(body, template=template)
        value['template']['nodes'][0]['label'] = 'changed'
        value['graph']['nodes'][0]['label'] = 'changed'
        self.assertEqual([body, template], before)
        self.assertFalse(value['modelExecuted'])
        self.assertFalse(value['edgeStabilityEstablished'])
        self.assertFalse(value['causalEffectsIdentified'])

    def test_future_feature_is_excluded_and_late_null_preserves_old_date(self):
        body = request()
        body['features'].extend([dict(body['features'][0], featureValue=2, recordedAt='2026-02-01'),
                                 dict(body['features'][0], featureValue=None, recordedAt='2025-12-01')])
        value = inspect_course_graph(body)
        apoe = next(row for row in value['graph']['nodes'] if row['id'] == 'APOE_E4_COUNT')
        self.assertEqual(apoe['observedAt'], '2025-01-01')

    def test_conflicting_ambiguous_no_visits_other_window_are_blocked(self):
        for mode in ('conflict', 'ambiguous', 'no-visits', 'window'):
            body = request()
            if mode == 'conflict':
                body['features'].append(dict(body['features'][0], featureValue=None))
            elif mode == 'ambiguous':
                body['visits'].append(dict(body['visits'][-1], visitCode='OTHER'))
            elif mode == 'no-visits':
                body['visits'] = []
            else:
                body['predictionWindowMonths'] = 12
            value = inspect_course_graph(body)
            self.assertTrue(value['qualityBlocked'])
            self.assertEqual(value['graph'], {'nodes': [], 'edges': [], 'paths': []})
            self.assertFalse(value['originalScoringEligible'])

    def test_invalid_request_is_rejected_before_inspection(self):
        body = request()
        body['subjectCode'] = 'REAL-001'
        with self.assertRaises(AgentContractError):
            inspect_course_graph(body)


if __name__ == '__main__':
    unittest.main()
