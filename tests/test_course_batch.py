import copy
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from python_service.course_batch import (prepare_course_batch, validate_batch_plan, execute_course_batch,
                                         inspect_course_batch, CourseBatchError, encoded, sha)
from python_service.course_client import CourseClient, CourseClientError
from python_service.course_interop import owned_lab
from python_service.course_protocol import CourseProtocolError
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload

ROOT=Path(__file__).resolve().parents[1]


def batch_input(count=2, window=24):
    tables={}
    for name in ('subjects','visits','features'):
        with (ROOT/f'fixtures/{name}.synthetic.csv').open(encoding='utf-8',newline='') as stream: rows=list(csv.reader(stream))
        selected=rows[:1]+[row for row in rows[1:] if row[0] in {f'DEMO-{i:03d}' for i in range(1,count+1)}]
        text=io.StringIO(newline='');csv.writer(text,lineterminator='\n').writerows(selected);tables[name]=text.getvalue()
    preview={'input_mode':'SYNTHETIC_TEST','dataVersion':'demo-batch-tests','predictionWindowMonths':window,'tables':tables}
    runs={f'DEMO-{i:03d}':f'run-batch-test-{i}' for i in range(1,count+1)}
    return preview,runs


def plan(count=2,window=24): return prepare_course_batch(*batch_input(count,window))


def client():
    value=Mock(spec=CourseClient)
    value.create.side_effect=lambda request,**kwargs:run_workflow(request,score_java_synthetic_payload)
    return value


class CourseBatchTests(unittest.TestCase):
    def test_prepare_is_deterministic_without_scoring_or_network(self):
        preview,runs=batch_input();before=copy.deepcopy(preview)
        with patch('python_service.demo_scoring.score_java_synthetic_payload',side_effect=AssertionError('SCORE')):
            a=prepare_course_batch(preview,runs);b=prepare_course_batch(preview,dict(reversed(list(runs.items()))))
        self.assertEqual(a,b);self.assertEqual(preview,before)
        self.assertFalse(a['businessPersisted']);self.assertFalse(a['clinicalValidityAssessed'])

    def test_run_mapping_must_cover_exact_subjects_and_use_unique_original_ids(self):
        preview,runs=batch_input()
        for mapping in ({}, {'DEMO-001':'run-one'},dict(runs,EXTRA='run-extra'),dict.fromkeys(runs,'run-same'),dict(runs,**{'DEMO-001':False})):
            with self.assertRaises((CourseBatchError,CourseProtocolError)):prepare_course_batch(preview,mapping)

    def test_placeholders_and_invalid_run_identifiers_are_not_allocated_for_caller(self):
        preview,runs=batch_input(1)
        for identifier in ('run-csv-DEMO-001','../raw','run-test?token=x'):
            with self.assertRaises((CourseBatchError,CourseProtocolError)):prepare_course_batch(preview,{'DEMO-001':identifier})

    def test_invalid_csv_and_non_synthetic_inputs_produce_no_plan(self):
        preview,runs=batch_input();preview['tables']['visits']=preview['tables']['visits'].replace('visitDate','wrongDate')
        with self.assertRaises(CourseBatchError):prepare_course_batch(preview,runs)
        preview,runs=batch_input();preview['input_mode']='REAL_RETROSPECTIVE_RESEARCH'
        with self.assertRaises(ValueError):prepare_course_batch(preview,runs)

    def test_plan_excludes_alias_and_keeps_null_preview_scores(self):
        value=plan();text=encoded(value).decode('utf-8')
        self.assertNotIn('合成档案',text);self.assertNotIn('alias',text)
        self.assertTrue(all(row['riskScore'] is None and row['predictionProduced'] is False for row in value['quality']))

    def test_tampered_plan_fails_before_directory_creation_or_network(self):
        value=plan();value['requests'][0]['visits'][0]['mmse']=0
        remote=client()
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'never'
            with self.assertRaises(CourseBatchError):execute_course_batch(value,remote,target)
            self.assertFalse(target.exists());self.assertEqual(remote.mock_calls,[])

    def test_quality_contract_and_scope_changes_are_rejected_even_if_rehashed(self):
        for key,replacement in [('quality',[]),('contractSha256','0'*64),('businessPersisted',True),('scope','REAL')]:
            value=plan();value[key]=replacement
            value['planDigest']=sha(encoded({k:v for k,v in value.items() if k!='planDigest'}))
            with self.assertRaises(CourseBatchError):validate_batch_plan(value)

    def test_duplicate_subjects_or_runs_and_mixed_versions_are_rejected(self):
        for key in ('subjectCode','runId','dataVersion','predictionWindowMonths'):
            value=plan();value['requests'][1][key]=value['requests'][0][key] if key in ('subjectCode','runId') else ('demo-other' if key=='dataVersion' else 12)
            with self.assertRaises((CourseBatchError,CourseProtocolError)):validate_batch_plan(value)

    def test_actual_csv_http_report_pipeline_preserves_results(self):
        with tempfile.TemporaryDirectory() as folder,owned_lab() as (url,server):
            target=Path(folder)/'run';summary=execute_course_batch(plan(),CourseClient(url),target)
            self.assertEqual(summary['status'],'FINISHED');self.assertEqual(summary['counts']['COMPLETED'],2)
            self.assertEqual(server.post_calls,2);self.assertEqual(len(server.store.runs),2)
            result=json.loads((target/'001.result.json').read_text(encoding='utf-8'))
            report=json.loads((target/'001.report.json').read_text(encoding='utf-8'))
            self.assertEqual(result['riskScore'],report['riskScore']);self.assertIn('非诊疗报告',(target/'001.report.html').read_text(encoding='utf-8'))
            self.assertEqual(inspect_course_batch(target),summary)

    def test_blocked_batches_finish_with_null_results_and_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'blocked';summary=execute_course_batch(plan(window=12),client(),target)
            self.assertEqual(summary['status'],'FINISHED');self.assertEqual(summary['counts']['BLOCKED'],2)
            self.assertIsNone(json.loads((target/'001.report.json').read_text(encoding='utf-8'))['riskScore'])

    def test_existing_directory_prevents_health_and_post(self):
        with tempfile.TemporaryDirectory() as folder:
            remote=client()
            with self.assertRaises(FileExistsError):execute_course_batch(plan(),remote,folder)
            self.assertEqual(remote.mock_calls,[])

    def test_health_mismatch_halts_without_submission(self):
        with tempfile.TemporaryDirectory() as folder,owned_lab('wrong-health') as (url,server):
            summary=execute_course_batch(plan(),CourseClient(url),Path(folder)/'run')
            self.assertEqual(summary['status'],'HALTED');self.assertEqual(summary['counts']['NOT_ATTEMPTED'],2)
            self.assertEqual(server.post_calls,0)

    def test_post_commit_disconnect_stops_following_items_without_retry(self):
        with tempfile.TemporaryDirectory() as folder,owned_lab('commit-drop') as (url,server):
            summary=execute_course_batch(plan(),CourseClient(url),Path(folder)/'run')
            self.assertEqual(summary['counts']['UNKNOWN'],1);self.assertEqual(summary['counts']['NOT_ATTEMPTED'],1)
            self.assertEqual(server.post_calls,1);self.assertEqual(len(server.store.runs),1)
            self.assertFalse(summary['resubmissionAuthorized'])

    def test_definite_error_stops_without_fabricating_report(self):
        with tempfile.TemporaryDirectory() as folder,owned_lab('error500') as (url,server):
            target=Path(folder)/'run';summary=execute_course_batch(plan(),CourseClient(url),target)
            self.assertEqual(summary['counts']['FAILED'],1);self.assertEqual(summary['counts']['NOT_ATTEMPTED'],1)
            self.assertEqual(server.post_calls,1);self.assertFalse((target/'001.result.json').exists())

    def test_identity_failure_keeps_no_untrusted_result(self):
        with tempfile.TemporaryDirectory() as folder,owned_lab('wrong-run') as (url,server):
            target=Path(folder)/'run';summary=execute_course_batch(plan(),CourseClient(url),target)
            self.assertEqual(summary['counts']['UNKNOWN'],1);self.assertFalse((target/'001.result.json').exists())
            self.assertEqual(server.post_calls,1)

    def test_intent_is_on_disk_before_call_and_interrupt_is_not_a_success(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'run';remote=client()
            def interrupt(request,**kwargs):
                events=(target/'events.jsonl').read_text(encoding='utf-8')
                self.assertIn('INTENT',events);self.assertIn(request['runId'],events)
                raise KeyboardInterrupt()
            remote.create.side_effect=interrupt
            with self.assertRaises(KeyboardInterrupt):execute_course_batch(plan(),remote,target)
            result=inspect_course_batch(target)
            self.assertEqual(result['status'],'INCOMPLETE');self.assertEqual(result['counts']['UNKNOWN'],1)
            self.assertEqual(result['counts']['NOT_ATTEMPTED'],1)

    def test_partial_last_journal_line_is_not_an_acknowledged_result(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'run';remote=client();remote.create.side_effect=KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):execute_course_batch(plan(),remote,target)
            with (target/'events.jsonl').open('ab') as stream:stream.write(b'{"event":"RESULT"')
            summary=inspect_course_batch(target)
            self.assertTrue(summary['journalTailIncomplete']);self.assertEqual(summary['counts']['UNKNOWN'],1)

    def test_modified_result_or_report_is_detected(self):
        for name in ('001.result.json','001.report.json','001.report.html'):
            with tempfile.TemporaryDirectory() as folder:
                target=Path(folder)/'run';execute_course_batch(plan(),client(),target)
                with (target/name).open('ab') as stream:stream.write(b' ')
                with self.assertRaises(CourseBatchError):inspect_course_batch(target)

    def test_reordered_or_added_journal_events_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'run';execute_course_batch(plan(),client(),target)
            journal=target/'events.jsonl';lines=journal.read_bytes().splitlines(keepends=True)
            journal.write_bytes(b''.join([lines[0],lines[2],lines[1],*lines[3:]]))
            with self.assertRaises(CourseBatchError):inspect_course_batch(target)

    def test_reporting_failure_retains_result_and_never_submits_next(self):
        from python_service.course_report import CourseReportError
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'run';remote=client()
            with patch('python_service.course_batch.build_course_report',side_effect=CourseReportError('REPORT_SIZE')):
                summary=execute_course_batch(plan(),remote,target)
            self.assertEqual(summary['status'],'HALTED');self.assertEqual(summary['counts']['COMPLETED'],1)
            self.assertEqual(summary['items'][0]['reportStatus'],'FAILED');self.assertTrue((target/'001.result.json').exists())
            self.assertEqual(remote.create.call_count,1)

    def test_false_result_from_client_is_revalidated(self):
        remote=client();remote.create.side_effect=lambda request,**kwargs:{'riskScore':1}
        with tempfile.TemporaryDirectory() as folder:
            summary=execute_course_batch(plan(),remote,Path(folder)/'run')
            self.assertEqual(summary['counts']['UNKNOWN'],1);self.assertEqual(remote.create.call_count,1)

    def test_client_cannot_modify_plan_during_create(self):
        value=plan();original=copy.deepcopy(value);remote=client()
        def mutate(request,**kwargs):
            result=run_workflow(request,score_java_synthetic_payload);request['subjectCode']='DEMO-OTHER';return result
        remote.create.side_effect=mutate
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(execute_course_batch(value,remote,Path(folder)/'run')['status'],'FINISHED')
        self.assertEqual(value,original)

    def test_cli_prepare_execute_and_inspect_without_overwrite(self):
        with tempfile.TemporaryDirectory() as folder,owned_lab() as (url,server):
            directory=Path(folder);source=directory/'input.json';prepared=directory/'plan.json';output=directory/'run'
            preview,runs=batch_input();source.write_text(json.dumps({'previewInput':preview,'runIds':runs}),encoding='utf-8')
            base=[sys.executable,'-B','-m','python_service.course_batch']
            command=base+['prepare','--input',str(source),'--output',str(prepared)]
            run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0);self.assertEqual(server.post_calls,0)
            run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,1)
            run=subprocess.run(base+['execute','--plan',str(prepared),'--url',url,'--output',str(output)],cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0);self.assertEqual(server.post_calls,2)
            run=subprocess.run(base+['inspect','--directory',str(output)],cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0);self.assertEqual(server.post_calls,2)
            self.assertNotIn('visits',run.stdout);self.assertNotIn('合成档案',run.stdout)
