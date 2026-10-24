"""Downstream tools must not run after an invalid or mutating stage."""
import copy
from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker
from python_service import deepagent_contract as workflow_module
from python_service.course_protocol import CourseContract, validate_course_result
from python_service.course_fusion import select_fusion
from python_service.course_graph import default_course_graph
from python_service.deepagent_contract import AgentContractError, graph_scoring_inputs, run_workflow
from python_service.demo_scoring import score_java_synthetic_payload
from python_service.server import AgentServer, RunStore

ROOT = Path(__file__).resolve().parents[1]


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


class StageBoundaryTests(unittest.TestCase):
    def assert_failed(self, body, scorer):
        with self.assertRaises(AgentContractError) as error:
            run_workflow(body, scorer)
        self.assertEqual((error.exception.status, error.exception.code), (500, 'ASSESSMENT_FAILED'))
        self.assertNotIn('PRIVATE_STAGE_DETAIL', str(error.exception))

    def test_fusion_cannot_rewrite_original_request_and_then_validate_against_it(self):
        body = request()
        original = copy.deepcopy(body)

        def mutating_fusion(payload):
            payload['visits'][-1]['mmse'] = 30
            return select_fusion(payload)

        with patch('python_service.deepagent_contract.select_fusion', side_effect=mutating_fusion), patch(
                'python_service.deepagent_contract.default_course_graph', wraps=default_course_graph) as graph, patch(
                'python_service.server.score_java_synthetic_payload', wraps=score_java_synthetic_payload) as scorer:
            self.assert_failed(body, scorer)
            graph.assert_not_called()
            scorer.assert_not_called()
        self.assertEqual(body, original)

    def test_graph_cannot_rewrite_selected_feature_sources_before_scoring(self):
        def mutating_graph(features):
            features['APOE_E4_COUNT']['featureValue'] = 2
            return default_course_graph(features)

        with patch('python_service.deepagent_contract.default_course_graph', side_effect=mutating_graph), patch(
                'python_service.server.score_java_synthetic_payload', wraps=score_java_synthetic_payload) as scorer:
            self.assert_failed(request(), scorer)
            scorer.assert_not_called()

    def test_invalid_graph_evidence_is_rejected_before_the_score_tool(self):
        def bad_graph(features):
            result = default_course_graph(features)
            result['edges'][0]['note'] = 'PRIVATE_STAGE_DETAIL'
            return result

        with patch('python_service.deepagent_contract.default_course_graph', side_effect=bad_graph), patch(
                'python_service.server.score_java_synthetic_payload', wraps=score_java_synthetic_payload) as scorer:
            self.assert_failed(request(), scorer)
            scorer.assert_not_called()

    def test_invalid_fusion_output_is_execution_500_before_downstream(self):
        with patch('python_service.deepagent_contract.select_fusion', return_value=None), patch(
                'python_service.deepagent_contract.default_course_graph') as graph, patch(
                'python_service.server.score_java_synthetic_payload', wraps=score_java_synthetic_payload) as scorer:
            self.assert_failed(request(), scorer)
            graph.assert_not_called()
            scorer.assert_not_called()

    def test_equal_score_cannot_hide_a_changed_gated_source(self):
        def wrong_sources(visits, features, graph):
            selected_visits, selected_features = graph_scoring_inputs(visits, features, graph)
            # Right MRI is context with left present; this still must not be
            # silently removed from the selected input evidence.
            selected_features = [row for row in selected_features if row['featureName'] != 'MRI_HIPPOCAMPUS_R']
            return selected_visits, selected_features

        with patch('python_service.deepagent_contract.graph_scoring_inputs', side_effect=wrong_sources), patch(
                'python_service.server.score_java_synthetic_payload', wraps=score_java_synthetic_payload) as scorer:
            self.assert_failed(request(), scorer)
            scorer.assert_not_called()

    def test_every_fusion_field_is_checked_before_graph_and_scoring(self):
        original = select_fusion(request())
        changes = {
            'indexDate': '2025-01-01', 'blocked': True,
            'hasCognition': False, 'missingModalities': ['APOE_E4_COUNT'],
            'excludedPostIndexFeatures': False, 'blockingReasons': ['fabricated'],
            'warningCodes': ['fabricated'], 'eligibleFeatures': [],
            'latest': original['visits'][0], 'visits': list(reversed(original['visits'])),
            'conflictingFeatures': True, 'ambiguousIndex': True,
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                selected = copy.deepcopy(original)
                selected[field] = value
                with patch('python_service.deepagent_contract.select_fusion', return_value=selected), patch(
                        'python_service.deepagent_contract.default_course_graph') as graph, patch(
                        'python_service.server.score_java_synthetic_payload', wraps=score_java_synthetic_payload) as scorer:
                    self.assert_failed(request(), scorer)
                    graph.assert_not_called()
                    scorer.assert_not_called()

    def test_fusion_cannot_suppress_a_real_conflict_and_continue(self):
        body = request()
        body['features'].append(dict(body['features'][0], featureValue=2))
        selected = select_fusion(body)
        selected.update(blocked=False, conflictingFeatures=False, blockingReasons=[])
        with patch('python_service.deepagent_contract.select_fusion', return_value=selected), patch(
                'python_service.deepagent_contract.default_course_graph') as graph, patch(
                'python_service.server.score_java_synthetic_payload') as scorer:
            self.assert_failed(body, scorer)
            graph.assert_not_called()
            scorer.assert_not_called()

    def test_fusion_same_score_source_date_change_is_rejected(self):
        selected = copy.deepcopy(select_fusion(request()))
        selected['features']['MRI_HIPPOCAMPUS_R']['recordedAt'] = '2024-12-31'
        with patch('python_service.deepagent_contract.select_fusion', return_value=selected), patch(
                'python_service.server.score_java_synthetic_payload') as scorer:
            self.assert_failed(request(), scorer)
            scorer.assert_not_called()

    def test_invalid_graph_fields_are_rejected_before_gate_and_score(self):
        canonical = default_course_graph(select_fusion(request())['features'])
        changed = []
        value = copy.deepcopy(canonical)
        value['nodes'][2]['observedAt'] = '2024-12-31'
        changed.append(value)
        value = copy.deepcopy(canonical)
        value['nodes'][0]['label'] = 'PRIVATE_STAGE_DETAIL'
        changed.append(value)
        value = copy.deepcopy(canonical)
        value['edges'][0]['status'] = 'MISSING'
        changed.append(value)
        value = copy.deepcopy(canonical)
        value['paths'][0]['nodes'].reverse()
        changed.append(value)
        value = copy.deepcopy(canonical)
        value['graphVersion'] = 'demo-alternative'
        changed.extend([value, None, [], {}])
        for graph_value in changed:
            with self.subTest(graph=graph_value):
                with patch('python_service.deepagent_contract.default_course_graph', return_value=graph_value), patch(
                        'python_service.deepagent_contract.graph_scoring_inputs') as gate, patch(
                        'python_service.server.score_java_synthetic_payload') as scorer:
                    self.assert_failed(request(), scorer)
                    gate.assert_not_called()
                    scorer.assert_not_called()

    def test_gate_cannot_mutate_checked_graph_even_with_correct_return_values(self):
        def changing_gate(visits, features, graph):
            result = graph_scoring_inputs(visits, features, graph)
            graph['edges'][0]['note'] = 'PRIVATE_STAGE_DETAIL'
            return result

        with patch('python_service.deepagent_contract.graph_scoring_inputs', side_effect=changing_gate), patch(
                'python_service.server.score_java_synthetic_payload') as scorer:
            self.assert_failed(request(), scorer)
            scorer.assert_not_called()

    def test_gate_source_reordering_duplication_and_wrong_shapes_are_rejected(self):
        selection = select_fusion(request())
        visits = copy.deepcopy(selection['visits'])
        features = [copy.deepcopy(selection['features'][name]) for name in sorted(selection['features'])]
        for output in ((list(reversed(visits)), features), (visits, list(reversed(features))),
                       (visits, features + [features[0]]), [visits, features], None, (visits,)):
            with self.subTest(output=output):
                with patch('python_service.deepagent_contract.graph_scoring_inputs', return_value=output), patch(
                        'python_service.server.score_java_synthetic_payload') as scorer:
                    self.assert_failed(request(), scorer)
                    scorer.assert_not_called()

    def test_internal_input_type_exceptions_from_each_stage_are_execution_500(self):
        for name in ('select_fusion', 'default_course_graph', 'graph_scoring_inputs'):
            for failure in (ValueError('PRIVATE_STAGE_DETAIL'),
                            AgentContractError('PRIVATE_STAGE_DETAIL', 409, 'AGENT_CONTRACT_MISMATCH')):
                with self.subTest(stage=name, failure=type(failure).__name__):
                    with patch('python_service.deepagent_contract.' + name, side_effect=failure), patch(
                            'python_service.server.score_java_synthetic_payload') as scorer:
                        self.assert_failed(request(), scorer)
                        scorer.assert_not_called()

    def test_score_tool_cannot_modify_input_after_computing_a_correct_result(self):
        def changing_score(payload):
            result = score_java_synthetic_payload(payload)
            payload['visits'][0]['visitCode'] = 'PRIVATE_STAGE_DETAIL'
            return result

        self.assert_failed(request(), changing_score)

    def test_mutating_caller_request_does_not_change_checked_stage_sources(self):
        body = request()
        expected = copy.deepcopy(body)

        def graph(features):
            body['visits'].clear()
            body['features'].clear()
            return default_course_graph(features)

        with patch('python_service.deepagent_contract.default_course_graph', side_effect=graph):
            result = run_workflow(body, score_java_synthetic_payload)
        validate_course_result(result, expected, CourseContract())

    def test_fusion_return_reference_is_detached_before_graph_call(self):
        supplied = select_fusion(request())

        def graph(features):
            supplied['features']['APOE_E4_COUNT']['featureValue'] = 2
            supplied['visits'][-1]['mmse'] = 30
            return default_course_graph(features)

        with patch('python_service.deepagent_contract.select_fusion', return_value=supplied), patch(
                'python_service.deepagent_contract.default_course_graph', side_effect=graph):
            result = run_workflow(request(), score_java_synthetic_payload)
        validate_course_result(result, request(), CourseContract())

    def test_graph_return_reference_is_detached_before_gating(self):
        supplied = default_course_graph(select_fusion(request())['features'])

        def gate(visits, features, graph):
            supplied['nodes'].clear()
            return graph_scoring_inputs(visits, features, graph)

        with patch('python_service.deepagent_contract.default_course_graph', return_value=supplied), patch(
                'python_service.deepagent_contract.graph_scoring_inputs', side_effect=gate):
            result = run_workflow(request(), score_java_synthetic_payload)
        validate_course_result(result, request(), CourseContract())

    def test_legacy_score_return_reference_is_detached_before_explanation(self):
        supplied = []
        real_stage = workflow_module._stage

        def tool(payload):
            result = score_java_synthetic_payload(payload)
            supplied.append(result)
            return result

        def stage(name, status, started, summary):
            if name == 'WARNING_MODEL':
                supplied[0]['explanations'].clear()
                supplied[0]['riskLevel'] = 'LOW'
            return real_stage(name, status, started, summary)

        with patch('python_service.deepagent_contract._stage', side_effect=stage):
            result = run_workflow(request(), tool)
        validate_course_result(result, request(), CourseContract())

    def test_blocked_stops_before_every_other_stage_tool(self):
        bodies = []
        empty = request()
        empty['visits'] = []
        bodies.append(empty)
        conflict = request()
        conflict['features'].append(dict(conflict['features'][0], featureValue=2))
        bodies.append(conflict)
        bodies.append(dict(request(), predictionWindowMonths=12))
        for body in bodies:
            with self.subTest(body=body):
                with patch('python_service.deepagent_contract.default_course_graph') as graph, patch(
                        'python_service.deepagent_contract.graph_scoring_inputs') as gate, patch(
                        'python_service.server.score_java_synthetic_payload') as scorer:
                    result = run_workflow(body, scorer)
                    self.assertEqual(result['status'], 'BLOCKED')
                    self.assertIsNone(result['riskScore'])
                    self.assertEqual(result['riskLevel'], 'UNAVAILABLE')
                    graph.assert_not_called()
                    gate.assert_not_called()
                    scorer.assert_not_called()

    def test_null_zero_fractional_and_mri_fallback_keep_original_selection(self):
        body = request()
        body['features'][1]['featureValue'] = None
        body['features'][2]['featureValue'] = 0
        body['visits'][-1].update(mmse=27.555, moca=None, cdrSb=0)
        result = run_workflow(body, score_java_synthetic_payload)
        validate_course_result(result, body, CourseContract())
        self.assertIn('MRI_HIPPOCAMPUS_L', result['missingModalities'])

    def test_normal_stage_order_executes_each_original_tool_once(self):
        with patch('python_service.deepagent_contract.select_fusion', wraps=select_fusion) as fusion, patch(
                'python_service.deepagent_contract.default_course_graph', wraps=default_course_graph) as graph, patch(
                'python_service.deepagent_contract.graph_scoring_inputs', wraps=graph_scoring_inputs) as gate, patch(
                'python_service.server.score_java_synthetic_payload', wraps=score_java_synthetic_payload) as scorer:
            result = run_workflow(request(), scorer)
            self.assertEqual([stage['stage'] for stage in result['stages']], list(workflow_module.STAGES))
            for tool in (fusion, graph, gate, scorer):
                self.assertEqual(tool.call_count, 1)


@contextmanager
def service():
    server = AgentServer(('127.0.0.1', 0), RunStore())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, server.store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def wire(port, method, body=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        path = '/api/agent/v1/runs' + ('/' + request()['runId'] if method == 'GET' else '')
        conn.request(method, path, json.dumps(body).encode() if body is not None else None,
                     {'Content-Type': 'application/json', 'X-Trace-Id': 'stage-boundaries-test'})
        response = conn.getresponse()
        value = json.loads(response.read())
        schema = CourseContract().schemas['AgentResult' if response.status == 200 else 'AgentError']
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
        return response.status, value
    finally:
        conn.close()


class StageHttpTests(unittest.TestCase):
    def test_actual_http_mutating_fusion_and_graph_fail_before_scoring_without_cache(self):
        def changing_fusion(payload):
            payload['visits'][-1]['mmse'] = 30
            return select_fusion(payload)

        def changing_graph(features):
            features['APOE_E4_COUNT']['featureValue'] = 2
            return default_course_graph(features)

        with service() as (port, store):
            for name, tool in (('select_fusion', changing_fusion), ('default_course_graph', changing_graph)):
                with self.subTest(stage=name), patch('python_service.deepagent_contract.' + name, side_effect=tool), patch(
                        'python_service.server.score_java_synthetic_payload') as scorer:
                    status, error = wire(port, 'POST', request())
                    self.assertEqual((status, error['code']), (500, 'ASSESSMENT_FAILED'))
                    self.assertEqual(error['traceId'], 'stage-boundaries-test')
                    scorer.assert_not_called()
                    self.assertEqual(store.runs, {})
                    self.assertEqual(store._pending, {})
                    self.assertEqual(wire(port, 'GET')[0], 404)
            self.assertEqual(wire(port, 'POST', request())[0], 200)

    def test_actual_http_bad_graph_and_gate_do_not_call_scorer_or_echo_private_text(self):
        def bad_graph(features):
            value = default_course_graph(features)
            value['nodes'][0]['label'] = 'PRIVATE_STAGE_DETAIL'
            return value

        with service() as (port, store):
            for name, config in (('default_course_graph', {'side_effect': bad_graph}),
                                 ('graph_scoring_inputs', {'return_value': ([], [])})):
                with self.subTest(stage=name), patch('python_service.deepagent_contract.' + name, **config), patch(
                        'python_service.server.score_java_synthetic_payload') as scorer:
                    status, error = wire(port, 'POST', request())
                    self.assertEqual((status, error['code']), (500, 'ASSESSMENT_FAILED'))
                    self.assertNotIn('PRIVATE_STAGE_DETAIL', json.dumps(error))
                    scorer.assert_not_called()
                    self.assertEqual(store.runs, {})
                    self.assertEqual(wire(port, 'GET')[0], 404)
            self.assertEqual(wire(port, 'POST', request())[0], 200)


if __name__ == '__main__':
    unittest.main()
