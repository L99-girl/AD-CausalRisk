"""Event-controlled checks for independent executions and duplicate failure fanout."""
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import http.client
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker
from python_service.course_protocol import CourseContract, validate_course_result
from python_service.deepagent_contract import AgentContractError, run_workflow
from python_service.demo_scoring import score_java_synthetic_payload
from python_service.server import AgentServer, RunStore, _PendingRun

ROOT = Path(__file__).resolve().parents[1]


def request(run_id='run-concurrent-slow'):
    value = json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))
    value['runId'] = run_id
    return value


@contextmanager
def held_execution(store, body=None, failure=None):
    body = body or request()
    entered, release = threading.Event(), threading.Event()

    def workflow(payload, tool):
        if payload['runId'] == body['runId']:
            entered.set()
            if not release.wait(10):
                raise RuntimeError('test did not release execution')
            if failure is not None:
                raise failure
        return run_workflow(payload, tool)

    with patch('python_service.server.run_workflow', side_effect=workflow) as mocked:
        with ThreadPoolExecutor(max_workers=12) as pool:
            leader = pool.submit(store.create, body)
            try:
                if not entered.wait(5):
                    raise AssertionError('leader did not enter workflow')
                yield pool, leader, release, mocked
            finally:
                release.set()


@contextmanager
def joined_requests(count):
    """Observe admission to an existing execution without timing sleeps."""
    entered = threading.Event()
    lock = threading.Lock()
    observed = 0
    original = _PendingRun.wait_result

    def wait_result(flight):
        nonlocal observed
        with lock:
            observed += 1
            if observed == count:
                entered.set()
        return original(flight)

    with patch.object(_PendingRun, 'wait_result', wait_result):
        yield entered


class StoreConcurrencyTests(unittest.TestCase):
    def assert_error(self, future, status, code):
        with self.assertRaises(AgentContractError) as caught:
            future.result(timeout=2)
        self.assertEqual((caught.exception.status, caught.exception.code), (status, code))
        self.assertNotIn('PRIVATE_TOOL_DETAIL', str(caught.exception))

    def test_completed_history_is_readable_while_another_run_executes(self):
        store = RunStore()
        expected = store.create(request('run-history'))
        with held_execution(store) as (pool, leader, release, _):
            self.assertEqual(pool.submit(store.get, 'run-history').result(timeout=2), expected)
            self.assertFalse(leader.done())

    def test_unrelated_run_finishes_without_waiting_for_slow_run(self):
        store = RunStore()
        with held_execution(store) as (pool, leader, release, _):
            result = pool.submit(store.create, request('run-independent')).result(timeout=2)
            self.assertEqual(result['runId'], 'run-independent')
            self.assertFalse(leader.done())

    def test_inflight_conflict_is_rejected_without_waiting(self):
        store = RunStore()
        with held_execution(store) as (pool, leader, release, _):
            body = request()
            body['predictionWindowMonths'] = 12
            self.assert_error(pool.submit(store.create, body), 409, 'RUN_ID_CONFLICT')
            self.assertFalse(leader.done())

    def test_capacity_includes_inflight_reservation_and_rejects_immediately(self):
        store = RunStore(capacity=1)
        with held_execution(store) as (pool, leader, release, _):
            self.assert_error(pool.submit(store.create, request('run-overflow')), 503, 'RUN_CAPACITY_REACHED')
            self.assertFalse(leader.done())

    def test_inflight_get_is_a_cache_miss_without_waiting_or_execution(self):
        store = RunStore()
        with held_execution(store) as (pool, leader, release, mocked):
            self.assert_error(pool.submit(store.get, request()['runId']), 404, 'RUN_NOT_FOUND')
            self.assertEqual(mocked.call_count, 1)
            self.assertFalse(leader.done())

    def test_eight_duplicates_share_one_execution_and_independent_result_copies(self):
        store = RunStore(capacity=1)
        with held_execution(store) as (pool, leader, release, mocked), joined_requests(8) as joined:
            followers = [pool.submit(store.create, request()) for _ in range(8)]
            self.assertTrue(joined.wait(5))
            self.assertTrue(all(not future.done() for future in followers))
            release.set()
            expected = leader.result(timeout=5)
            results = [future.result(timeout=5) for future in followers]
            self.assertEqual(results, [expected] * 8)
            self.assertEqual(mocked.call_count, 1)
            results[0]['graph']['nodes'].clear()
            expected['warnings'].append('changed')
            self.assertTrue(results[1]['graph']['nodes'])
            self.assertNotIn('changed', store.get(request()['runId'])['warnings'])

    def test_json_key_order_is_the_same_inflight_request(self):
        store = RunStore()
        with held_execution(store) as (pool, leader, release, mocked), joined_requests(1) as joined:
            body = dict(reversed(list(request().items())))
            body['visits'] = [dict(reversed(list(row.items()))) for row in body['visits']]
            follower = pool.submit(store.create, body)
            self.assertTrue(joined.wait(5))
            release.set()
            self.assertEqual(follower.result(timeout=5), leader.result(timeout=5))
            self.assertEqual(mocked.call_count, 1)

    def check_failure_fanout(self, failure):
        store = RunStore(capacity=1)
        with held_execution(store, failure=failure) as (pool, leader, release, mocked), joined_requests(6) as joined:
            followers = [pool.submit(store.create, request()) for _ in range(6)]
            self.assertTrue(joined.wait(5))
            release.set()
            for future in [leader, *followers]:
                self.assert_error(future, 500, 'ASSESSMENT_FAILED')
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(store.runs, {})
            self.assertEqual(store._pending, {})
        # Only this new, explicit call starts another attempt after the failure.
        self.assertEqual(store.create(request())['status'], 'COMPLETED')

    def test_workflow_failure_is_shared_without_retry_or_private_detail(self):
        self.check_failure_fanout(ValueError('PRIVATE_TOOL_DETAIL'))

    def test_execution_contract_error_is_not_misreported_as_input_error(self):
        self.check_failure_fanout(AgentContractError('PRIVATE_TOOL_DETAIL', 409, 'AGENT_CONTRACT_MISMATCH'))

    def test_invalid_result_failure_is_shared_and_capacity_is_released(self):
        store = RunStore(capacity=1)
        entered, release = threading.Event(), threading.Event()

        def bad_workflow(body, tool):
            entered.set()
            self.assertTrue(release.wait(5))
            result = run_workflow(body, tool)
            result['riskScore'] = None
            return result

        with ThreadPoolExecutor(max_workers=4) as pool, patch('python_service.server.run_workflow', side_effect=bad_workflow) as mocked:
            leader = pool.submit(store.create, request())
            try:
                self.assertTrue(entered.wait(5))
                with joined_requests(2) as joined:
                    followers = [pool.submit(store.create, request()) for _ in range(2)]
                    self.assertTrue(joined.wait(5))
                    release.set()
                    for future in [leader, *followers]:
                        self.assert_error(future, 500, 'ASSESSMENT_FAILED')
                    self.assertEqual(mocked.call_count, 1)
            finally:
                release.set()
        self.assertEqual(store.runs, {})
        self.assertEqual(store.create(request('run-new-after-failure'))['status'], 'COMPLETED')

    def test_thread_interruption_releases_followers_and_reservation(self):
        store = RunStore(capacity=1)
        with held_execution(store, failure=SystemExit('PRIVATE_TOOL_DETAIL')) as (pool, leader, release, mocked), joined_requests(1) as joined:
            follower = pool.submit(store.create, request())
            self.assertTrue(joined.wait(5))
            release.set()
            with self.assertRaises(SystemExit):
                leader.result(timeout=5)
            self.assert_error(follower, 500, 'ASSESSMENT_FAILED')
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(store._pending, {})
        self.assertEqual(store.create(request())['status'], 'COMPLETED')

    def test_capacity_reservation_is_atomic_for_competing_new_runs(self):
        store = RunStore(capacity=1)
        with held_execution(store) as (pool, leader, release, mocked):
            futures = [pool.submit(store.create, request('run-capacity-' + str(i))) for i in range(8)]
            for future in futures:
                self.assert_error(future, 503, 'RUN_CAPACITY_REACHED')
            self.assertEqual(mocked.call_count, 1)

    def test_full_capacity_still_allows_completed_replay_during_other_execution(self):
        store = RunStore(capacity=2)
        expected = store.create(request('run-history'))
        with held_execution(store) as (pool, leader, release, _):
            replay = pool.submit(store.create, request('run-history'))
            self.assertEqual(replay.result(timeout=2), expected)
            self.assertFalse(leader.done())

    def test_blocked_duplicates_share_null_result_without_scoring(self):
        store = RunStore()
        body = request()
        body['visits'] = []
        with patch('python_service.server.score_java_synthetic_payload') as scorer:
            with held_execution(store, body) as (pool, leader, release, mocked), joined_requests(2) as joined:
                followers = [pool.submit(store.create, body) for _ in range(2)]
                self.assertTrue(joined.wait(5))
                release.set()
                result = leader.result(timeout=5)
                self.assertEqual([future.result(timeout=5) for future in followers], [result] * 2)
                self.assertEqual(mocked.call_count, 1)
            scorer.assert_not_called()
        self.assertIsNone(result['riskScore'])
        self.assertEqual(result['riskLevel'], 'UNAVAILABLE')
        self.assertEqual([stage['stage'] for stage in result['stages']], ['DATA_FUSION'])

    def test_waiting_request_owns_its_snapshot_before_caller_changes_it(self):
        store = RunStore()
        with held_execution(store) as (pool, leader, release, _), joined_requests(1) as joined:
            body = request()
            follower = pool.submit(store.create, body)
            self.assertTrue(joined.wait(5))
            body['visits'].clear()
            body['dataVersion'] = 'demo-mutated'
            release.set()
            self.assertEqual(follower.result(timeout=5), leader.result(timeout=5))

    def test_validated_snapshot_is_published_even_if_external_workflow_return_changes(self):
        store = RunStore()
        source = run_workflow(request(), score_java_synthetic_payload)
        expected = copy.deepcopy(source)

        def check_snapshot(value, body, contract):
            # The workflow still owns its reference; mutate that reference
            # after the store acquired its own copy, before validation.
            source['riskScore'] = None
            source['explanations'].clear()
            validate_course_result(value, body, contract)

        with patch('python_service.server.run_workflow', return_value=source), patch(
                'python_service.server.validate_course_result', side_effect=check_snapshot):
            self.assertEqual(store.create(request()), expected)
        self.assertEqual(store.get(request()['runId']), expected)

    def test_distinct_concurrent_inputs_keep_their_own_scores_and_versions(self):
        store = RunStore()
        bodies = [request('run-isolated-' + str(i)) for i in range(6)]
        for index, body in enumerate(bodies):
            body['dataVersion'] = 'demo-isolated-' + str(index)
            body['visits'][-1]['mmse'] = 20 + index
        barrier = threading.Barrier(len(bodies))

        def workflow(body, tool):
            barrier.wait(timeout=5)
            return run_workflow(body, tool)

        with patch('python_service.server.run_workflow', side_effect=workflow), ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(store.create, bodies))
        for body, result in zip(bodies, results):
            validate_course_result(result, body, CourseContract())
            self.assertEqual(store.get(body['runId']), result)
        self.assertEqual(len(store.runs), 6)


@contextmanager
def service(store):
    server = AgentServer(('127.0.0.1', 0), store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def http_call(port, method, body=None, run_id=None):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        path = '/api/agent/v1/runs' + ('/' + run_id if run_id else '')
        raw = json.dumps(body).encode() if body is not None else None
        connection.request(method, path, raw, {'Content-Type': 'application/json', 'X-Trace-Id': 'concurrency-test'})
        response = connection.getresponse()
        value = json.loads(response.read())
        schema = CourseContract().schemas['AgentResult' if response.status == 200 else 'AgentError']
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
        return response.status, value
    finally:
        connection.close()


class HttpConcurrencyTests(unittest.TestCase):
    def test_http_history_and_independent_post_work_while_another_post_executes(self):
        store = RunStore()
        history = store.create(request('run-history'))
        with service(store) as port, held_execution(store) as (pool, leader, release, _):
            self.assertEqual(pool.submit(http_call, port, 'GET', run_id='run-history').result(timeout=3), (200, history))
            self.assertEqual(pool.submit(http_call, port, 'POST', request('run-other-http')).result(timeout=3)[0], 200)
            self.assertFalse(leader.done())

    def test_http_inflight_conflict_capacity_and_cache_miss_are_immediate(self):
        store = RunStore(capacity=1)
        with service(store) as port, held_execution(store) as (pool, leader, release, _):
            changed = request()
            changed['predictionWindowMonths'] = 12
            for method, body, run_id, status, code in (
                    ('POST', changed, None, 409, 'RUN_ID_CONFLICT'),
                    ('POST', request('run-overflow'), None, 503, 'RUN_CAPACITY_REACHED'),
                    ('GET', None, request()['runId'], 404, 'RUN_NOT_FOUND')):
                actual, error = pool.submit(http_call, port, method, body, run_id).result(timeout=3)
                self.assertEqual((actual, error['code']), (status, code))
                self.assertEqual(error['traceId'], 'concurrency-test')
            self.assertFalse(leader.done())

    def test_http_duplicate_posts_share_original_result_and_duration(self):
        store = RunStore(capacity=1)
        with service(store) as port, held_execution(store) as (pool, leader, release, mocked), joined_requests(3) as joined:
            followers = [pool.submit(http_call, port, 'POST', request()) for _ in range(3)]
            self.assertTrue(joined.wait(5))
            release.set()
            expected = leader.result(timeout=5)
            self.assertEqual([future.result(timeout=5) for future in followers], [(200, expected)] * 3)
            self.assertEqual(http_call(port, 'GET', run_id=request()['runId']), (200, expected))
            self.assertEqual(mocked.call_count, 1)

    def test_http_duplicate_failures_do_not_execute_again_or_cache_a_result(self):
        store = RunStore(capacity=1)
        with service(store) as port:
            with held_execution(store, failure=ValueError('PRIVATE_TOOL_DETAIL')) as (pool, leader, release, mocked), joined_requests(3) as joined:
                followers = [pool.submit(http_call, port, 'POST', request()) for _ in range(3)]
                self.assertTrue(joined.wait(5))
                release.set()
                with self.assertRaises(AgentContractError):
                    leader.result(timeout=5)
                for future in followers:
                    status, error = future.result(timeout=5)
                    self.assertEqual((status, error['code']), (500, 'ASSESSMENT_FAILED'))
                    self.assertNotIn('PRIVATE_TOOL_DETAIL', json.dumps(error))
                self.assertEqual(mocked.call_count, 1)
            self.assertEqual(http_call(port, 'GET', run_id=request()['runId'])[0], 404)
            self.assertEqual(http_call(port, 'POST', request())[0], 200)


if __name__ == '__main__':
    unittest.main()
