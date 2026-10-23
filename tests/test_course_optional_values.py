"""Contract-optional numbers stay missing through fusion, scoring and evidence."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator, FormatChecker

from python_service.course_acceptance import owned_service, without_timing
from python_service.course_client import CourseClient, CourseClientError
from python_service.course_fusion import select_fusion, build_fusion_matrix
from python_service.course_graph import inspect_course_graph
from python_service.course_missingness import prepare_missingness_requests, validate_missingness_plan
from python_service.course_missingness_review import review_missingness_results
from python_service.course_path_evidence import build_course_path_evidence
from python_service.course_protocol import CourseContract, validate_course_request, validate_course_result
from python_service.course_report import build_course_report, render_course_html
from python_service.deepagent_contract import AgentContractError, payload_digest, request_identity_digest, request_snapshot, run_workflow
from python_service.demo_scoring import score_java_synthetic_payload
from python_service.server import RunStore

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('mmse', 'moca', 'cdrSb')


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


def omit(body=None, mask=63):
    body = copy.deepcopy(request() if body is None else body)
    for row in body['visits']:
        for bit, name in enumerate(FIELDS):
            if mask & (1 << bit): row.pop(name, None)
    for bit, row in enumerate(body['features']):
        if mask & (1 << (bit + 3)): row.pop('featureValue', None)
    return body


def explicit_null(body):
    body = copy.deepcopy(body)
    for row in body['visits']:
        for name in FIELDS: row.setdefault(name, None)
    for row in body['features']: row.setdefault('featureValue', None)
    return body


def result(body): return run_workflow(body, score_java_synthetic_payload)


class OptionalFusionTests(unittest.TestCase):
    def test_64_optional_combinations_are_schema_valid_and_match_explicit_null_controls(self):
        validator = Draft202012Validator(CourseContract().schemas['AgentRequest'], format_checker=FormatChecker())
        for mask in range(64):
            with self.subTest(mask=mask):
                body = omit(mask=mask); validator.validate(body)
                validate_course_request(body, CourseContract())
                actual = result(body)
                validate_course_result(actual, body, CourseContract())
                self.assertEqual(without_timing(actual), without_timing(result(explicit_null(body))))

    def test_optional_missing_feature_is_missing_not_zero(self):
        body = omit(mask=8)
        value = result(body)
        self.assertEqual(value['status'], 'COMPLETED')
        self.assertEqual(value['qualityStatus'], 'WARN')
        self.assertIn('APOE_E4_COUNT', value['missingModalities'])
        self.assertNotIn('APOE_E4_COUNT', [row['feature'] for row in value['explanations']])

    def test_omitted_later_feature_retains_older_observed_source(self):
        body = request(); late = dict(body['features'][1], recordedAt='2025-12-01')
        del late['featureValue']; body['features'].append(late)
        selected = select_fusion(request_snapshot(body))
        self.assertEqual(selected['features']['MRI_HIPPOCAMPUS_L'], body['features'][1])
        self.assertEqual(without_timing(result(body)), without_timing(result(explicit_null(body))))

    def test_same_day_observed_and_omitted_feature_is_original_conflict(self):
        body = request(); row = copy.deepcopy(body['features'][0]); del row['featureValue']
        body['features'].append(row)
        with patch('python_service.deepagent_contract.default_course_graph') as graph, patch(
                'python_service.deepagent_contract.graph_scoring_inputs') as gate:
            value = result(body)
        self.assertEqual(value['status'], 'BLOCKED'); self.assertIsNone(value['riskScore'])
        self.assertIn('CONFLICTING_FEATURE_VALUES', select_fusion(body)['blockingReasons'])
        graph.assert_not_called(); gate.assert_not_called()

    def test_equal_same_day_omitted_rows_do_not_create_observations_or_conflicts(self):
        body = omit(mask=8); body['features'].append(copy.deepcopy(body['features'][0]))
        value = select_fusion(body)
        self.assertFalse(value['conflictingFeatures'])
        self.assertNotIn('APOE_E4_COUNT', value['features'])
        self.assertEqual(result(body)['status'], 'COMPLETED')

    def test_post_index_omitted_value_is_excluded(self):
        body = request(); body['features'].append(dict(featureName='APOE_E4_COUNT', unit='count', recordedAt='2026-02-01'))
        value = result(body)
        self.assertEqual(value['stages'][0]['summary']['excludedPostIndexFeatures'], 1)
        self.assertEqual(value['riskScore'], .8304)

    def test_omitted_left_mri_uses_observed_right_mri(self):
        body = omit(mask=16); value = result(body)
        path = build_course_path_evidence(body, value)
        sources = {row['id']: row for row in path['sourceNodes']}
        term = next(row for row in path['termNodes'] if row['feature'] == 'MRI_HIPPOCAMPUS')
        self.assertEqual({sources[key]['featureName'] for key in term['sourceIds']}, {'MRI_HIPPOCAMPUS_R'})
        self.assertEqual(path['contextOnlySources'], [])

    def test_no_core_values_is_blocked_without_scoring(self):
        body = omit()
        with patch('python_service.server.score_java_synthetic_payload') as scorer:
            value = RunStore().create(body)
        scorer.assert_not_called()
        self.assertEqual(value['status'], 'BLOCKED')
        self.assertIsNone(value['riskScore']); self.assertEqual(value['riskLevel'], 'UNAVAILABLE')
        self.assertEqual([s['stage'] for s in value['stages']], ['DATA_FUSION'])

    def test_omission_does_not_change_zero_or_required_field_validation(self):
        body = omit(mask=8); body['visits'][-1]['mmse'] = 0; body['features'][1]['featureValue'] = 0
        self.assertEqual(result(body)['status'], 'COMPLETED')
        for name in ('featureName', 'unit', 'recordedAt'):
            changed = copy.deepcopy(body); del changed['features'][0][name]
            with self.subTest(name=name), self.assertRaises(AgentContractError): request_snapshot(changed)

    def test_omitted_index_cognition_does_not_backfill_from_old_visit(self):
        body = request()
        for field in FIELDS: del body['visits'][-1][field]
        with patch('python_service.deepagent_contract.default_course_graph') as graph:
            value = result(body)
        self.assertEqual(value['status'], 'BLOCKED'); graph.assert_not_called()
        self.assertIsNone(value['riskScore'])

    def test_no_visits_and_omitted_features_have_no_invented_index(self):
        body = omit(mask=56); body['visits'] = []
        value = result(body)
        self.assertEqual(value['status'], 'BLOCKED')
        self.assertIsNone(value['stages'][0]['summary']['indexDate'])
        self.assertEqual(value['stages'][0]['summary']['excludedPostIndexFeatures'], 3)


class OptionalProvenanceTests(unittest.TestCase):
    def test_request_identity_and_content_preserve_absence_and_null_difference(self):
        body = omit(mask=8); original = json.dumps(body)
        self.assertNotEqual(request_identity_digest(body), request_identity_digest(explicit_null(body)))
        self.assertNotEqual(payload_digest(body), payload_digest(explicit_null(body)))
        self.assertEqual(json.dumps(body), original)
        self.assertNotIn('featureValue', body['features'][0])

    def test_actual_client_replay_get_and_explicit_null_conflict(self):
        body = omit(mask=8)
        with owned_service() as (url, store):
            client = CourseClient(url); first = client.create(body)
            self.assertEqual(client.create(body), first)
            self.assertEqual(client.result(body['runId']), first)
            with self.assertRaises(CourseClientError) as caught: client.create(explicit_null(body))
            self.assertEqual((caught.exception.http_status, caught.exception.code), (409, 'RUN_ID_CONFLICT'))
            self.assertEqual(len(store.runs), 1)
            self.assertNotIn('featureValue', client._requests[body['runId']]['features'][0])

    def test_path_ignores_absent_feature_fields_and_every_source_pointer_resolves(self):
        body = request(); row = dict(body['features'][0], recordedAt='2025-12-01'); del row['featureValue']
        body['features'].insert(0, row)
        path = build_course_path_evidence(body, result(body))
        for source in path['sourceNodes'] + path['contextOnlySources']:
            table, index, field = source['jsonPointer'].strip('/').split('/')
            self.assertIn(field, body[table][int(index)])
            self.assertEqual(body[table][int(index)][field], source['value'])
            self.assertIsNotNone(source['value'])
        self.assertNotIn('features:1:featureValue', {s['id'] for s in path['sourceNodes']})

    def test_matrix_marks_absent_field_locations_without_inventing_value(self):
        body = omit(mask=9)
        value = build_fusion_matrix([body])
        row = value['rows'][0]
        for name in ('mmse', 'APOE_E4_COUNT'):
            for point in row['evidence'][name]['points']:
                self.assertEqual(point['state'], 'MISSING'); self.assertIsNone(point['value'])
                self.assertTrue(all(source['fieldPresent'] is False for source in point['sources']))
        self.assertIsNone(row['values']['mmse.latestObserved'])
        self.assertIsNone(row['values']['APOE_E4_COUNT.latestObserved'])
        self.assertNotIn('featureValue', body['features'][0])

    def test_matrix_explicit_null_has_existing_field_and_original_source_shape(self):
        body = explicit_null(omit(mask=8))
        point = build_fusion_matrix([body])['rows'][0]['evidence']['APOE_E4_COUNT']['points'][0]
        self.assertEqual(point['sources'], [{'table': 'features', 'recordIndex': 1, 'field': 'featureValue'}])
        self.assertEqual(point['state'], 'MISSING')

    def test_graph_inspection_has_missing_node_without_model_call(self):
        value = inspect_course_graph(omit(mask=16))
        self.assertEqual(next(n for n in value['graph']['nodes'] if n['id'] == 'MRI_HIPPOCAMPUS_L')['status'], 'MISSING')
        self.assertFalse(value['modelExecuted'])

    def test_missingness_plan_counts_removed_rows_separately_from_observed_values(self):
        body = omit(mask=8)
        plan = prepare_missingness_requests([body], ['run-optional-mask-' + str(i) for i in range(8)])
        self.assertEqual(validate_missingness_plan(plan), plan)
        genetics = plan['scenarios'][2]
        self.assertEqual(genetics['removedFeatureRows'], 1)
        self.assertEqual(genetics['removedFeatureValues'], 0)
        self.assertNotIn('featureValue', plan['baseRequests'][0]['features'][0])
        self.assertNotIn('featureValue', plan['scenarios'][0]['request']['features'][0])

    def test_missingness_review_handles_original_omitted_fields_and_source_maps(self):
        body = omit(mask=24)
        plan = prepare_missingness_requests([body], ['run-optional-review-' + str(i) for i in range(8)])
        values = [result(row['request']) for row in plan['scenarios']]
        review = review_missingness_results(plan, values)
        self.assertEqual(review['upstreamCourseResultsCompared'], 8)
        self.assertEqual(review['rows'][2]['scoreDelta'], 0)
        self.assertIsNone(review['rows'][1]['scoreDelta'])
        self.assertFalse(review['scoringExecutedByThisCall'])

    def test_existing_report_preserves_omission_and_renders_it_as_missing(self):
        body = omit(mask=8); value = result(explicit_null(body))
        report = build_course_report(body, value)
        self.assertNotIn('featureValue', report['sources']['features'][0])
        html = render_course_html(body, value)
        self.assertIn('缺失', html)
        self.assertFalse(report['modelExecutedByReport'])

    def test_matrix_duplicate_omissions_and_nulls_are_missing_not_observed(self):
        body = omit(mask=8)
        body['features'] += [copy.deepcopy(body['features'][0]), dict(body['features'][0], featureValue=None)]
        value = build_fusion_matrix([body])['rows'][0]['evidence']['APOE_E4_COUNT']
        self.assertEqual(value['missingRows'], 3)
        self.assertEqual(value['observedDates'], 0)
        self.assertEqual(value['ambiguousDates'], 0)
        self.assertEqual(value['equalFeatureRepeatRows'], 2)
        self.assertEqual(sum(source.get('fieldPresent') is False for source in value['points'][0]['sources']), 2)


if __name__ == '__main__': unittest.main()
