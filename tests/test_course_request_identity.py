"""Exact numeric equivalence for replay, without changing content provenance."""
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import math
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from python_service.course_client import CourseClient, CourseClientError
from python_service.deepagent_contract import AgentContractError, payload_digest, run_workflow
from python_service.demo_scoring import score_java_synthetic_payload
from python_service.server import AgentServer, RunStore, _PendingRun

ROOT = Path(__file__).resolve().parents[1]


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


def numeric_variant(body):
    body = copy.deepcopy(body)
    for row in body['visits']:
        for name in ('mmse', 'moca', 'cdrSb'):
            if row.get(name) is not None:
                row[name] = float(row[name])
    for row in body['features']:
        if row['featureName'] != 'APOE_E4_COUNT' and row['featureValue'] is not None:
            row['featureValue'] = float(row['featureValue'])
    return body


@contextmanager
def service():
    server = AgentServer(('127.0.0.1', 0))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield CourseClient('http://127.0.0.1:' + str(server.server_port)), server.store
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)


@contextmanager
def pending(store, body, *, failure=False, followers=1):
    entered, joined, release = threading.Event(), threading.Event(), threading.Event()
    count, lock = 0, threading.Lock()
    wait_original = _PendingRun.wait_result

    def workflow(value, tool):
        entered.set()
        if not release.wait(10): raise RuntimeError('test release missing')
        if failure: raise ValueError('PRIVATE_IDENTITY_TEST_DETAIL')
        return run_workflow(value, tool)

    def wait(flight):
        nonlocal count
        with lock:
            count += 1
            if count == followers: joined.set()
        return wait_original(flight)

    with patch('python_service.server.run_workflow', side_effect=workflow) as work, patch.object(
            _PendingRun, 'wait_result', wait), ThreadPoolExecutor(max_workers=6) as pool:
        leader = pool.submit(store.create, body)
        try:
            if not entered.wait(3): raise AssertionError('leader did not start')
            yield pool, leader, joined, release, work
        finally:
            release.set()


class RequestIdentityTests(unittest.TestCase):
    def test_completed_numeric_equivalent_replay_uses_one_execution(self):
        body = request(); store = RunStore()
        with patch('python_service.server.run_workflow', wraps=run_workflow) as work:
            expected = store.create(body)
            self.assertEqual(store.create(numeric_variant(body)), expected)
            self.assertEqual(work.call_count, 1)
        self.assertEqual(store.get(body['runId']), expected)

    def test_reverse_numeric_replay_preserves_first_execution_input_types(self):
        body = request(); first = numeric_variant(body); store = RunStore()
        with patch('python_service.server.run_workflow', wraps=run_workflow) as work:
            expected = store.create(first)
            self.assertEqual(store.create(body), expected)
            self.assertIs(type(work.call_args.args[0]['visits'][0]['mmse']), float)
            self.assertEqual(work.call_count, 1)

    def test_signed_zero_and_integral_mri_are_equivalent(self):
        body = request()
        body['visits'][-1].update(mmse=0, moca=0, cdrSb=0)
        body['features'][1]['featureValue'] = 0
        body['features'][2]['featureValue'] = 1
        changed = numeric_variant(body)
        changed['visits'][-1]['mmse'] = -0.0
        changed['features'][1]['featureValue'] = -0.0
        store = RunStore()
        self.assertEqual(store.create(body), store.create(changed))

    def test_capacity_does_not_block_equivalent_cached_replay(self):
        body = request(); store = RunStore(capacity=1)
        expected = store.create(body)
        self.assertEqual(store.create(numeric_variant(body)), expected)
        self.assertEqual(len(store.runs), 1)

    def test_equivalent_blocked_replay_never_calls_score(self):
        body = dict(request(), predictionWindowMonths=12); store = RunStore()
        with patch('python_service.server.score_java_synthetic_payload') as scorer:
            expected = store.create(body)
            self.assertEqual(store.create(numeric_variant(body)), expected)
            scorer.assert_not_called()
        self.assertIsNone(expected['riskScore'])
        self.assertEqual(expected['riskLevel'], 'UNAVAILABLE')

    def test_adjacent_float_same_score_is_still_a_conflict(self):
        body = request(); changed = numeric_variant(body)
        changed['visits'][-1]['mmse'] = math.nextafter(25.0, math.inf)
        self.assertEqual(run_workflow(body, score_java_synthetic_payload)['riskScore'],
                         run_workflow(changed, score_java_synthetic_payload)['riskScore'])
        store = RunStore(); store.create(body)
        with self.assertRaises(AgentContractError) as caught: store.create(changed)
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'RUN_ID_CONFLICT'))

    def test_context_dates_versions_missing_values_and_array_order_stay_distinct(self):
        body = request(); store = RunStore(); expected = store.create(body)
        mutations = [lambda b: b.update(dataVersion='demo-other'),
                     lambda b: b['features'][2].update(featureValue=.37),
                     lambda b: b['features'][2].update(recordedAt='2024-12-31'),
                     lambda b: b['visits'][0].update(moca=None),
                     lambda b: b['visits'].reverse(), lambda b: b['features'].reverse(),
                     lambda b: b['visits'][0].update(visitCode='Different')]
        for mutate in mutations:
            changed = numeric_variant(body); mutate(changed)
            with self.subTest(changed=changed['runId']):
                with self.assertRaises(AgentContractError) as caught: store.create(changed)
                self.assertEqual(caught.exception.status, 409)
        self.assertEqual(store.get(body['runId']), expected)

    def test_strict_integer_domains_are_validated_before_cache_replay(self):
        body = request(); store = RunStore(); store.create(body)
        for field in ('apoe', 'window'):
            changed = numeric_variant(body)
            if field == 'apoe': changed['features'][0]['featureValue'] = 1.0
            else: changed['predictionWindowMonths'] = 24.0
            with self.subTest(field=field):
                with self.assertRaises(AgentContractError) as caught: store.create(changed)
                self.assertEqual(caught.exception.status, 400)

    def test_content_digest_still_distinguishes_numeric_representation(self):
        body = request(); changed = numeric_variant(body)
        self.assertNotEqual(payload_digest(body), payload_digest(changed))
        before = json.dumps(changed)
        store = RunStore(); store.create(body)
        self.assertEqual(store.create(changed)['runId'], body['runId'])
        self.assertEqual(json.dumps(changed), before)

    def test_numeric_replay_returns_independent_copy(self):
        body = request(); store = RunStore(); expected = store.create(body)
        actual = store.create(numeric_variant(body))
        actual['graph']['nodes'].clear()
        actual['riskScore'] = None
        self.assertEqual(store.get(body['runId']), expected)

    def test_request_identity_is_exact_and_keeps_missing_distinct_from_null(self):
        from python_service.deepagent_contract import request_identity_digest
        body = request(); changed = numeric_variant(body)
        self.assertEqual(request_identity_digest(body), request_identity_digest(changed))
        changed['visits'][0]['mmse'] = math.nextafter(28.0, math.inf)
        self.assertNotEqual(request_identity_digest(body), request_identity_digest(changed))
        absent = request(); del absent['visits'][0]['moca']
        null = copy.deepcopy(absent); null['visits'][0]['moca'] = None
        self.assertNotEqual(request_identity_digest(absent), request_identity_digest(null))

    def test_first_snapshot_and_content_are_never_normalized_in_place(self):
        from python_service.deepagent_contract import request_identity_digest
        body = numeric_variant(request()); before = json.dumps(body)
        request_identity_digest(body)
        self.assertEqual(json.dumps(body), before)
        self.assertIs(type(body['visits'][0]['mmse']), float)


class ClientIdentityTests(unittest.TestCase):
    def test_actual_client_equivalent_create_keeps_first_snapshot(self):
        body = request()
        with service() as (client, store):
            first = client.create(body)
            self.assertEqual(client.create(numeric_variant(body)), first)
            self.assertIs(type(client._requests[body['runId']]['visits'][0]['mmse']), int)
            self.assertEqual(len(store.runs), 1)

    def test_actual_client_get_accepts_equivalent_explicit_baseline(self):
        body = request()
        with service() as (client, _):
            first = client.create(body)
            self.assertEqual(client.result(body['runId'], expected_request=numeric_variant(body)), first)

    def test_client_real_value_change_is_rejected_before_get(self):
        body = request(); client = CourseClient(); client._requests[body['runId']] = copy.deepcopy(body)
        changed = numeric_variant(body); changed['features'][2]['featureValue'] = math.nextafter(.36, math.inf)
        with patch.object(client, 'health') as health, patch.object(client, '_request') as network:
            with self.assertRaises(CourseClientError) as caught:
                client.result(body['runId'], expected_request=changed)
        self.assertEqual(caught.exception.code, 'REQUEST_BINDING_MISMATCH')
        health.assert_not_called(); network.assert_not_called()

    def test_client_integer_domain_violation_is_rejected_before_network(self):
        for field in ('apoe', 'window'):
            body = request(); client = CourseClient()
            if field == 'apoe': body['features'][0]['featureValue'] = 1.0
            else: body['predictionWindowMonths'] = 24.0
            with self.subTest(field=field), patch.object(client, 'health') as health:
                with self.assertRaises(CourseClientError) as caught: client.create(body)
                self.assertEqual(caught.exception.code, 'INVALID_REQUEST')
                self.assertEqual(client._requests, {}); health.assert_not_called()


class ConcurrentIdentityTests(unittest.TestCase):
    def test_inflight_numeric_variants_share_original_execution(self):
        body = request(); store = RunStore(capacity=1)
        with pending(store, body, followers=3) as (pool, leader, joined, release, work):
            futures = [pool.submit(store.create, numeric_variant(body)) for _ in range(3)]
            self.assertTrue(joined.wait(3))
            release.set(); expected = leader.result(timeout=4)
            self.assertEqual([f.result(timeout=4) for f in futures], [expected] * 3)
            self.assertEqual(work.call_count, 1)

    def test_inflight_numeric_variants_share_failure_without_recompute(self):
        body = request(); store = RunStore(capacity=1)
        with pending(store, body, failure=True, followers=2) as (pool, leader, joined, release, work):
            futures = [pool.submit(store.create, numeric_variant(body)) for _ in range(2)]
            self.assertTrue(joined.wait(3)); release.set()
            for future in [leader, *futures]:
                with self.assertRaises(AgentContractError) as caught: future.result(timeout=4)
                self.assertEqual(caught.exception.status, 500)
                self.assertNotIn('PRIVATE_IDENTITY', str(caught.exception))
            self.assertEqual(work.call_count, 1)
        self.assertEqual(store.runs, {}); self.assertEqual(store._pending, {})

    def test_inflight_actual_value_change_remains_immediate_conflict(self):
        body = request(); store = RunStore(capacity=1)
        with pending(store, body) as (pool, leader, _, release, _):
            changed = numeric_variant(body); changed['visits'][-1]['mmse'] = math.nextafter(25.0, math.inf)
            future = pool.submit(store.create, changed)
            with self.assertRaises(AgentContractError) as caught: future.result(timeout=2)
            self.assertEqual(caught.exception.status, 409)
            self.assertFalse(leader.done()); release.set()

    def test_stage_mutation_checks_keep_exact_content_identity(self):
        from python_service.course_fusion import select_fusion
        def tool(body):
            body['visits'][0]['mmse'] = float(body['visits'][0]['mmse'])
            return select_fusion(body)
        with patch('python_service.deepagent_contract.select_fusion', side_effect=tool), patch(
                'python_service.deepagent_contract.default_course_graph') as graph:
            with self.assertRaises(AgentContractError) as caught: run_workflow(request(), score_java_synthetic_payload)
        self.assertEqual(caught.exception.status, 500); graph.assert_not_called()

    def test_equivalent_waiters_do_not_consume_another_capacity_slot(self):
        body = request(); store = RunStore(capacity=1)
        with pending(store, body) as (pool, leader, joined, release, work):
            duplicate = pool.submit(store.create, numeric_variant(body))
            self.assertTrue(joined.wait(3))
            unrelated = dict(request(), runId='run-identity-no-capacity')
            with self.assertRaises(AgentContractError) as caught: store.create(unrelated)
            self.assertEqual(caught.exception.status, 503)
            with self.assertRaises(AgentContractError) as caught: store.get(body['runId'])
            self.assertEqual(caught.exception.status, 404)
            self.assertFalse(leader.done()); release.set()
            self.assertEqual(duplicate.result(timeout=4), leader.result(timeout=4))
            self.assertEqual(work.call_count, 1)


if __name__ == '__main__': unittest.main()
