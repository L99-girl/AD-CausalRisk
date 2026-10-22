"""Exact input lineage, original-history rules and score reconstruction."""
import copy
from fractions import Fraction
import itertools
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from python_service.course_path_evidence import build_course_path_evidence
from python_service.course_graph import GraphEvidenceError
from python_service.course_fusion import build_fusion_matrix
from python_service.course_protocol import CourseProtocolError
from python_service.deepagent_contract import run_workflow, AgentContractError, payload_digest
from python_service.demo_scoring import score_java_synthetic_payload

ROOT = Path(__file__).resolve().parents[1]


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


def evidence(body=None):
    body = request() if body is None else body
    result = run_workflow(body, score_java_synthetic_payload)
    return build_course_path_evidence(body, result)


def term(value, name):
    return next(row for row in value['termNodes'] if row['feature'] == name)


class PathEvidenceTests(unittest.TestCase):
    def assert_sources_match(self, body, value):
        ids = set()
        for source in value['sourceNodes'] + value['contextOnlySources']:
            self.assertNotIn(source['id'], ids)
            ids.add(source['id'])
            row = body[source['collection']][source['recordIndex'] - 1]
            self.assertEqual(source['value'], row[source['field']])
            self.assertEqual(source['observedAt'], row.get('recordedAt', row.get('visitDate')))
            self.assertLessEqual(source['observedAt'], value['indexDate'])
            self.assertIsNone(source['availableAt'])
            self.assertEqual(source['jsonPointer'], f"/{source['collection']}/{source['recordIndex'] - 1}/{source['field']}")
        all_nodes = {row['id'] for row in value['sourceNodes'] + value['termNodes']}
        if value['outputNode']:
            all_nodes.add(value['outputNode']['id'])
        for edge in value['edges']:
            self.assertIn(edge['from'], all_nodes)
            self.assertIn(edge['to'], all_nodes)
        for row in value['termNodes']:
            self.assertTrue(row['sourceIds'])
            self.assertTrue(set(row['sourceIds']) <= {source['id'] for source in value['sourceNodes']})

    def test_original_terms_and_each_typed_source_bound_for_100_profiles(self):
        bodies = json.loads((ROOT / 'fixtures/synthetic_subjects_100.json').read_text(encoding='utf-8'))['subjects']
        for body in bodies:
            result = run_workflow(body, score_java_synthetic_payload)
            value = build_course_path_evidence(body, result)
            self.assertEqual(value['eligibilityGraph'], result['graph'])
            self.assertEqual(value['requestSha256'], payload_digest(body))
            self.assertEqual(value['resultSha256'], payload_digest(result))
            self.assertEqual(value['upstreamResultScore'], result['riskScore'])
            self.assertEqual({row['feature']: row['contribution'] for row in value['termNodes']},
                             {row['feature']: row['contribution'] for row in result['explanations']})
            self.assert_sources_match(body, value)
            self.assertTrue(value['reconstruction']['algebraMatchesValidatedScore'])

    def test_all_64_missing_combinations_preserve_sources_or_block(self):
        for cognition, modalities in itertools.product(range(8), repeat=2):
            body = request()
            for bit, field in enumerate(('mmse', 'moca', 'cdrSb')):
                if cognition & (1 << bit):
                    body['visits'][-1][field] = None
            body['features'] = [row for bit, row in enumerate(body['features']) if not modalities & (1 << bit)]
            value = evidence(body)
            self.assert_sources_match(body, value)
            if cognition == 7:
                self.assertEqual(value['paths'], [])
                self.assertIsNone(value['reconstruction'])
            else:
                self.assertEqual(len(value['paths']), len(value['termNodes']))

    def test_zero_is_a_real_term_source_and_path_weight(self):
        body = request()
        body['features'][0]['featureValue'] = 0
        value = evidence(body)
        row = term(value, 'APOE_E4_COUNT')
        self.assertEqual(row['rawContribution'], 0)
        self.assertEqual(row['contribution'], 0)
        self.assertNotIn('APOE_E4_COUNT', value['missingTerms'])
        self.assertTrue(any(edge['weight'] == 0 for edge in value['edges'] if edge['kind'] == 'ADDITIVE_TERM'))

    def test_left_mri_source_and_context_only_right_not_double_counted(self):
        value = evidence()
        row = term(value, 'MRI_HIPPOCAMPUS')
        self.assertEqual(row['sourceIds'], ['features:2:featureValue'])
        self.assertEqual(value['contextOnlySources'][0]['featureName'], 'MRI_HIPPOCAMPUS_R')
        self.assertNotIn('features:3:featureValue', {edge['from'] for edge in value['edges']})
        self.assertEqual(sum(path['termId'] == 'term:MRI_HIPPOCAMPUS' for path in value['paths']), 1)

    def test_right_mri_fallback_when_left_missing(self):
        body = request()
        body['features'] = [row for row in body['features'] if row['featureName'] != 'MRI_HIPPOCAMPUS_L']
        value = evidence(body)
        self.assertEqual(term(value, 'MRI_HIPPOCAMPUS')['sourceIds'], ['features:2:featureValue'])
        self.assertEqual(value['contextOnlySources'], [])
        self.assertTrue(any(source.get('featureName') == 'MRI_HIPPOCAMPUS_R' for source in value['sourceNodes']))

    def test_left_zero_keeps_preference_over_right(self):
        body = request()
        body['features'][1]['featureValue'] = 0
        value = evidence(body)
        self.assertEqual(term(value, 'MRI_HIPPOCAMPUS')['sourceIds'], ['features:2:featureValue'])
        self.assertEqual(term(value, 'MRI_HIPPOCAMPUS')['contribution'], .07)

    def test_equal_duplicates_all_referenced_once_in_one_contribution(self):
        body = request()
        body['features'].append(dict(body['features'][0]))
        value = evidence(body)
        self.assertEqual(term(value, 'APOE_E4_COUNT')['sourceIds'],
                         ['features:1:featureValue', 'features:4:featureValue'])
        self.assertEqual(sum(edge['kind'] == 'ADDITIVE_TERM' and edge['from'] == 'term:APOE_E4_COUNT'
                             for edge in value['edges']), 1)
        self.assert_sources_match(body, value)

    def test_late_null_and_future_feature_not_used_as_source(self):
        body = request()
        body['features'].extend([dict(body['features'][0], featureValue=None, recordedAt='2025-12-01'),
                                 dict(body['features'][0], featureValue=2, recordedAt='2026-02-01')])
        value = evidence(body)
        self.assertEqual(term(value, 'APOE_E4_COUNT')['sourceIds'], ['features:1:featureValue'])
        self.assertNotIn('features:4:featureValue', {row['id'] for row in value['sourceNodes']})
        self.assertNotIn('features:5:featureValue', {row['id'] for row in value['sourceNodes']})

    def test_latest_missing_mmse_is_not_backfilled(self):
        body = request()
        body['visits'][-1]['mmse'] = None
        value = evidence(body)
        self.assertEqual(value['missingTerms']['MMSE'], 'INDEX_COGNITION_MISSING')
        self.assertEqual(value['missingTerms']['MMSE_DELTA'], 'INDEX_MMSE_MISSING')
        self.assertFalse(any(row['field'] == 'mmse' for row in value['sourceNodes'] if row['collection'] == 'visits'))

    def test_single_visit_and_first_mmse_missing_keep_specific_reasons(self):
        body = request()
        body['visits'] = body['visits'][-1:]
        self.assertEqual(evidence(body)['missingTerms']['MMSE_DELTA'], 'INSUFFICIENT_VISITS')
        body = request()
        body['visits'][0]['mmse'] = None
        self.assertEqual(evidence(body)['missingTerms']['MMSE_DELTA'], 'FIRST_OBSERVED_MMSE_MISSING')

    def test_no_modalities_does_not_create_zero_apoe_or_mri_term(self):
        body = request()
        body['features'] = []
        value = evidence(body)
        self.assertEqual(value['missingTerms']['APOE_E4_COUNT'], 'NO_ELIGIBLE_APOE_OBSERVATION')
        self.assertEqual(value['missingTerms']['MRI_HIPPOCAMPUS'], 'NO_ELIGIBLE_MRI_OBSERVATION')

    def test_full_original_history_not_descriptive_lookback(self):
        body = request()
        body['visits'].insert(0, dict(body['visits'][0], visitCode='EARLY', visitDate='2020-01-01', mmse=30))
        value = evidence(body)
        self.assertEqual(term(value, 'MMSE_DELTA')['sourceIds'], ['visits:1:mmse', 'visits:3:mmse'])
        self.assertEqual(term(value, 'MMSE_DELTA')['contribution'], .14)
        matrix = build_fusion_matrix([body])
        self.assertEqual(matrix['rows'][0]['values']['mmse.firstObserved'], 28)
        self.assertEqual(next(row['value'] for row in value['sourceNodes'] if row['id'] == 'visits:1:mmse'), 30)

    def test_shuffled_arrays_keep_original_indices_not_sorted_positions(self):
        body = request()
        body['visits'].reverse()
        body['features'].reverse()
        value = evidence(body)
        self.assertEqual(term(value, 'MMSE')['sourceIds'], ['visits:1:mmse'])
        self.assertEqual(term(value, 'MMSE_DELTA')['sourceIds'], ['visits:2:mmse', 'visits:1:mmse'])
        self.assertEqual(term(value, 'MRI_HIPPOCAMPUS')['sourceIds'], ['features:2:featureValue'])
        self.assert_sources_match(body, value)

    def test_unrounded_direction_differs_from_rounded_term_threshold(self):
        body = request()
        body['visits'][-1]['mmse'] = 26.9796
        row = term(evidence(body), 'MMSE')
        self.assertEqual(row['contribution'], .002)
        self.assertGreater(row['rawContribution'], .002)
        self.assertEqual(row['direction'], 'UP')

    def test_independent_fraction_arithmetic_and_nonzero_rounding_residual(self):
        body = request()
        body['visits'][-1].update(mmse=27, moca=24, cdrSb=.4)
        value = evidence(body)
        raw = Fraction('0.18') + Fraction(1, 12) + Fraction('.04') + Fraction(1, 30) + Fraction('.045') + Fraction('.0154')
        r = value['reconstruction']
        self.assertAlmostEqual(r['unroundedScoreBeforeClipping'], float(raw))
        self.assertNotEqual(r['wireRoundingResidual'], 0)
        self.assertLessEqual(abs(r['wireRoundingResidual']), r['maximumWireRoundingDifference'])

    def test_lower_and_upper_clipping_explained_without_changing_terms(self):
        for upper in (False, True):
            body = request()
            for visit in body['visits']:
                visit.update(mmse=0 if upper else 30, moca=0 if upper else 30, cdrSb=18 if upper else 0)
            if upper:
                body['visits'][0]['mmse'] = 30
            for feature in body['features']:
                feature['featureValue'] = (2 if upper else 0) if feature['featureName'] == 'APOE_E4_COUNT' else (0 if upper else 1)
            r = evidence(body)['reconstruction']
            self.assertEqual(r['returnedScore'], .95 if upper else .05)
            self.assertNotEqual(r['clippingAdjustment'], 0)
            self.assertTrue(r['algebraMatchesValidatedScore'])

    def test_blocked_all_reasons_produce_no_usable_graph_or_score(self):
        for mode in ('no-visits', 'conflict', 'ambiguous', 'window', 'cognition'):
            body = request()
            if mode == 'no-visits':
                body['visits'] = []
            elif mode == 'conflict':
                body['features'].append(dict(body['features'][0], featureValue=2))
            elif mode == 'ambiguous':
                body['visits'].append(dict(body['visits'][-1], visitCode='OTHER'))
            elif mode == 'window':
                body['predictionWindowMonths'] = 12
            else:
                body['visits'][-1].update(mmse=None, moca=None, cdrSb=None)
            value = evidence(body)
            for field in ('sourceNodes', 'termNodes', 'edges', 'paths', 'contextOnlySources'):
                self.assertEqual(value[field], [])
            self.assertIsNone(value['outputNode'])
            self.assertIsNone(value['reconstruction'])
            self.assertIsNone(value['upstreamResultScore'])
            self.assertEqual(set(value['missingTerms'].values()), {'QUALITY_BLOCKED'})

    def test_tampered_valid_schema_result_and_versions_rejected(self):
        body = request()
        original = run_workflow(body, score_java_synthetic_payload)
        for field, content in (('runId', 'run-other'), ('dataVersion', 'demo-other'),
                               ('modelVersion', 'wrong'), ('riskScore', .5)):
            result = dict(original, **{field: content})
            with self.assertRaises(CourseProtocolError):
                build_course_path_evidence(body, result)
        result = copy.deepcopy(original)
        result['explanations'][0]['contribution'] += .01
        with self.assertRaises(CourseProtocolError):
            build_course_path_evidence(body, result)

    def test_invalid_private_subject_and_invalid_json_rejected(self):
        body = request()
        result = run_workflow(body, score_java_synthetic_payload)
        body['subjectCode'] = 'PRIVATE-001'
        with self.assertRaises(AgentContractError):
            build_course_path_evidence(body, result)
        result['warnings'] = ['\ud800']
        with self.assertRaises(GraphEvidenceError):
            build_course_path_evidence(request(), result)

    def test_oversized_result_rejected_before_copying(self):
        body = request()
        result = run_workflow(body, score_java_synthetic_payload)
        result['warnings'] = ['x' * (512 * 1024)]
        with self.assertRaisesRegex(GraphEvidenceError, 'GRAPH_INPUT_SIZE'):
            build_course_path_evidence(body, result)

    def test_adaptation_has_no_scorer_calls_and_no_aliases(self):
        body = request()
        result = run_workflow(body, score_java_synthetic_payload)
        before = copy.deepcopy([body, result])
        with patch('python_service.demo_scoring.score_java_synthetic_payload', side_effect=AssertionError('no scoring')):
            value = build_course_path_evidence(body, result)
        self.assertEqual([body, result], before)
        value['eligibilityGraph']['nodes'][0]['label'] = 'edited'
        value['limitations'].append('edited')
        value['sourceNodes'][0]['value'] = 999
        self.assertEqual([body, result], before)
        for key in ('modelExecuted', 'modelFitted', 'predictionProduced', 'persisted',
                    'historicalAvailabilityVerified', 'edgeStabilityEstablished', 'causalEffectsIdentified', 'clinicalValidityAssessed'):
            self.assertFalse(value[key])
        json.dumps(value, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
