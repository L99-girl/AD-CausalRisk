import copy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from python_service.course_clock import BUSINESS_TIMEZONE, business_today
from python_service.course_client import CourseClient, CourseClientError
from python_service.course_csv import prepare_csv
from python_service.course_protocol import CourseContract, validate_course_result
from python_service.deepagent_contract import AgentContractError, validate_request
from python_service.server import AgentServer


ROOT = Path(__file__).resolve().parents[1]
INSTANT = datetime(2026, 10, 23, 16, 30, tzinfo=timezone.utc)
TODAY = date(2026, 10, 24)


def request():
    body = json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))
    body['visits'][-1]['visitDate'] = TODAY.isoformat()
    for feature in body['features']:
        feature['recordedAt'] = TODAY.isoformat()
    return body


def csv_request():
    return {'input_mode': 'SYNTHETIC_TEST', 'dataVersion': 'demo-business-day',
            'predictionWindowMonths': 24, 'tables': {
                'subjects': 'subjectCode,alias,status\nDEMO-001,Synthetic,ACTIVE\n',
                'visits': 'subjectCode,visitCode,visitDate,mmse,moca,cdrSb\n'
                          'DEMO-001,BL,2025-01-01,28,25,0.5\n'
                          'DEMO-001,M12,2026-10-24,25,22,1.5\n',
                'features': 'subjectCode,featureName,featureValue,recordedAt,unit\n'
                            'DEMO-001,APOE_E4_COUNT,1,2026-10-24,count\n'}}


class BusinessDayTests(unittest.TestCase):
    def test_business_day_at_midnight_leap_month_and_year_boundaries(self):
        for instant, expected in (
            ('2026-10-23T15:59:59+00:00', '2026-10-23'),
            ('2026-10-23T16:00:00+00:00', '2026-10-24'),
            ('2026-10-24T00:00:00+00:00', '2026-10-24'),
            ('2024-02-28T16:00:00+00:00', '2024-02-29'),
            ('2024-02-29T16:00:00+00:00', '2024-03-01'),
            ('2026-12-31T16:00:00+00:00', '2027-01-01'),
        ):
            with self.subTest(instant=instant), patch('python_service.course_clock.datetime', wraps=datetime) as clock:
                clock.now.side_effect = lambda zone: datetime.fromisoformat(instant).astimezone(zone)
                self.assertEqual(business_today().isoformat(), expected)

    def test_request_and_csv_ignore_both_earlier_and_later_host_dates(self):
        for host_day in (date(2026, 10, 23), TODAY, date(2026, 10, 25)):
            class HostDate(date):
                @classmethod
                def today(cls):
                    return host_day
            with self.subTest(host=host_day), patch('python_service.course_clock.datetime', wraps=datetime) as clock, \
                    patch('python_service.deepagent_contract.date', HostDate), patch('python_service.course_csv.date', HostDate):
                clock.now.side_effect = lambda zone: INSTANT.astimezone(zone)
                body = request(); original = copy.deepcopy(body)
                validate_request(body)
                preview, typed = prepare_csv(csv_request())
                self.assertEqual(preview['errorCount'], 0)
                self.assertEqual(len(typed), 1)
                self.assertEqual(body, original)
                for table, field in (('visits', 'visitDate'), ('features', 'recordedAt')):
                    future = copy.deepcopy(body); future[table][-1][field] = '2026-10-25'
                    with self.assertRaises(AgentContractError):
                        validate_request(future)
                    csv_body = csv_request(); csv_body['tables'][table] = csv_body['tables'][table].replace('2026-10-24', '2026-10-25')
                    invalid, requests = prepare_csv(csv_body)
                    self.assertEqual(invalid['status'], 'INVALID')
                    self.assertEqual(requests, [])

    def test_request_uses_one_day_if_midnight_passes_between_fields(self):
        body = request()
        with patch('python_service.course_clock.datetime', wraps=datetime) as clock:
            clock.now.side_effect = [datetime(2026, 10, 23, 15, 59, 59, tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE),
                                     INSTANT.astimezone(BUSINESS_TIMEZONE)]
            with self.assertRaises(AgentContractError):
                validate_request(body)
            self.assertEqual(clock.now.call_count, 1)

    def test_csv_rows_use_one_day_if_midnight_passes_during_parsing(self):
        with patch('python_service.course_clock.datetime', wraps=datetime) as clock:
            clock.now.side_effect = [datetime(2026, 10, 23, 15, 59, 59, tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE),
                                     INSTANT.astimezone(BUSINESS_TIMEZONE)]
            preview, typed = prepare_csv(csv_request())
            self.assertEqual(preview['status'], 'INVALID')
            self.assertEqual(typed, [])
            self.assertEqual(clock.now.call_count, 1)

    def test_real_http_client_cache_replay_and_get_use_same_business_day(self):
        with patch('python_service.course_clock.datetime', wraps=datetime) as clock:
            clock.now.side_effect = lambda zone: INSTANT.astimezone(zone)
            server = AgentServer(('127.0.0.1', 0))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                client = CourseClient('http://127.0.0.1:' + str(server.server_port))
                body = request(); result = client.create(body)
                self.assertEqual(result['status'], 'COMPLETED')
                validate_course_result(result, body, CourseContract())
                self.assertEqual(client.create(body), result)
                self.assertEqual(client.result(body['runId']), result)
                fresh = CourseClient('http://127.0.0.1:' + str(server.server_port))
                self.assertEqual(fresh.result(body['runId'], expected_request=body), result)
            finally:
                server.shutdown(); thread.join(); server.server_close()

    def test_future_dates_stop_before_client_http_and_server_workflow(self):
        with patch('python_service.course_clock.datetime', wraps=datetime) as clock:
            clock.now.side_effect = lambda zone: INSTANT.astimezone(zone)
            client = CourseClient()
            for table, field in (('visits', 'visitDate'), ('features', 'recordedAt')):
                body = request(); body[table][-1][field] = '2026-10-25'
                with patch.object(client, '_request') as send:
                    with self.assertRaises(CourseClientError):
                        client.create(body)
                    send.assert_not_called()
                self.assertEqual(client._requests, {})
            server = AgentServer(('127.0.0.1', 0))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                with patch('python_service.server.run_workflow') as workflow:
                    for table, field in (('visits', 'visitDate'), ('features', 'recordedAt')):
                        body = request(); body[table][-1][field] = '2026-10-25'
                        call = Request('http://127.0.0.1:' + str(server.server_port) + '/api/agent/v1/runs',
                                       data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
                        with self.assertRaises(HTTPError) as raised:
                            urlopen(call, timeout=5)
                        response = raised.exception
                        with response:
                            self.assertEqual(response.code, 400)
                            error = json.load(response)
                        self.assertEqual(error['code'], 'VALIDATION_400')
                        CourseContract().validate('AgentError', error)
                    workflow.assert_not_called()
                self.assertEqual(server.store.runs, {})
                self.assertEqual(server.store._pending, {})
            finally:
                server.shutdown(); thread.join(); server.server_close()


if __name__ == '__main__':
    unittest.main()
