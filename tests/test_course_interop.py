import copy
import http.client
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from python_service.course_interop import (build_interop_pack, vector_requests, FaultLabServer,
                                           owned_lab, run_interop_acceptance, source_hashes)
from python_service.course_client import CourseClient
from python_service.course_protocol import CourseContract, validate_course_request

ROOT=Path(__file__).resolve().parents[1]


class CourseInteropTests(unittest.TestCase):
    def test_export_is_deterministic_and_contains_no_dynamic_durations(self):
        a,b=build_interop_pack(),build_interop_pack()
        self.assertEqual(a,b);self.assertEqual(len(a['cases']),6)
        self.assertTrue(all('durationMs' not in stage for case in a['cases'] for stage in case['expectedCore']['stages']))

    def test_six_original_contract_valid_requests_include_preserved_precision(self):
        contract=CourseContract();requests=dict(vector_requests())
        for request in requests.values():validate_course_request(request,contract)
        self.assertEqual(requests['fractional']['visits'][-1]['mmse'],25.44)
        self.assertEqual(requests['fractional']['visits'][-1]['moca'],22.123456)
        self.assertEqual(requests['zero']['visits'][-1]['mmse'],0)

    def test_cores_have_known_original_score_and_blocked_null(self):
        cases={case['id']:case for case in build_interop_pack()['cases']}
        self.assertEqual(cases['completed']['expectedCore']['riskScore'],.8304)
        for name in ('blocked-window','blocked-cognition'):
            self.assertIsNone(cases[name]['expectedCore']['riskScore'])
            self.assertEqual(cases[name]['expectedCore']['riskLevel'],'UNAVAILABLE')
        self.assertEqual(cases['warn-missing']['expectedCore']['qualityStatus'],'WARN')

    def test_export_does_not_mutate_original_example_or_share_references(self):
        source=ROOT/'contracts/examples/deepagent-v1.request.example.json';before=source.read_bytes()
        pack=build_interop_pack();pack['cases'][0]['request']['visits'][0]['mmse']=0
        self.assertEqual(source.read_bytes(),before)
        self.assertEqual(build_interop_pack()['cases'][0]['request']['visits'][0]['mmse'],28)

    def test_pack_distinguishes_test_oracles_and_business_acceptance(self):
        pack=build_interop_pack()
        self.assertFalse(pack['javaIntegrationValidated']);self.assertFalse(pack['clinicalValidityAssessed'])
        self.assertEqual(pack['contractSha256'],CourseContract().sha256)
        self.assertEqual(pack['sourceSha256'],source_hashes())
        self.assertTrue(all(row['automaticResubmissionAllowed'] is False for row in pack['faultExpectations']))

    def test_fault_servers_only_bind_ephemeral_loopback_and_close(self):
        with owned_lab() as (url,server):
            self.assertEqual(server.server_address[0],'127.0.0.1')
            self.assertNotIn(server.server_port,(8084,8091,8092))
            port=server.server_port
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=2)
            connection.request('GET','/api/health');response=connection.getresponse()
            self.assertEqual(response.getheader('X-Course-Fault-Lab'),'synthetic-test-only')
            self.assertEqual(json.loads(response.read())['serviceMode'],'COURSE_SYNTHETIC');connection.close()
        with socket.socket() as connection:
            connection.settimeout(.5);self.assertNotEqual(connection.connect_ex(('127.0.0.1',port)),0)

    def test_unknown_scenario_rejected_before_server_creation(self):
        with self.assertRaises(ValueError):FaultLabServer('production')

    def test_fault_lab_still_rejects_browser_preflight(self):
        with owned_lab('ok') as (url,server):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
            connection.request('OPTIONS','/api/agent/v1/runs');response=connection.getresponse()
            self.assertEqual(response.status,405);self.assertIsNone(response.getheader('Access-Control-Allow-Origin'))
            self.assertEqual(json.loads(response.read())['code'],'METHOD_NOT_ALLOWED');connection.close()

    def test_lab_store_replays_original_and_preserves_actual_elapsed_time(self):
        with owned_lab() as (url,server):
            client=CourseClient(url);request=vector_requests()[0][1];result=client.create(request)
            self.assertEqual(client.create(request),result);self.assertEqual(len(server.store.runs),1)
            self.assertGreaterEqual(result['stages'][0]['durationMs'],0)

    def test_cli_export_uses_no_server_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'pack.json'
            command=[sys.executable,'-B','-m','python_service.course_interop','--export',str(output)]
            run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0);self.assertIn('"networkRequests": 0',run.stdout)
            original=output.read_bytes();self.assertEqual(len(json.loads(original)['cases']),6)
            run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,1);self.assertEqual(output.read_bytes(),original)

    def test_actual_faults_post_commit_recovery_and_original_process_restart(self):
        result=run_interop_acceptance()
        self.assertEqual(result['passed'],16);self.assertEqual(len(result['faultObservations']),11)
        self.assertTrue(result['originalServerProcessesRestarted'])
        self.assertFalse(result['originalApiOrScoringChanged']);self.assertFalse(result['javaIntegrationValidated'])
