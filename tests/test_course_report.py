import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from python_service.course_report import build_course_report, render_course_html, CourseReportError
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload

ROOT = Path(__file__).resolve().parents[1]


def pair():
    return tuple(json.loads((ROOT/'contracts/examples'/name).read_text(encoding='utf-8')) for name in ('deepagent-v1.request.example.json','deepagent-v1.response.example.json'))


class CourseReportTests(unittest.TestCase):
    def test_original_example_preserves_score_versions_source_values_and_duration(self):
        request, result = pair(); report = build_course_report(request, result)
        self.assertEqual(report['riskScore'], .8304)
        self.assertEqual(report['sources'], {'visits': request['visits'], 'features': request['features']})
        for key in ('modelVersion','workflowVersion','contractVersion','dataVersion','runId'): self.assertEqual(report[key], result[key])
        self.assertEqual([r['durationMs'] for r in report['stages']], [r['durationMs'] for r in result['stages']])

    def test_report_does_not_call_score_or_modify_inputs(self):
        request, result = pair(); before = copy.deepcopy((request, result))
        with patch('python_service.deepagent_contract.run_workflow', side_effect=AssertionError('CALLED')), patch('python_service.demo_scoring.score_java_synthetic_payload', side_effect=AssertionError('CALLED')):
            report = build_course_report(request, result)
        self.assertEqual((request,result), before)
        self.assertFalse(report['modelExecutedByReport']); self.assertFalse(report['persisted'])

    def test_teaching_omits_inputs_graph_numeric_contributions_and_internal_stages(self):
        request, result = pair(); report = build_course_report(request,result,audience='teaching')
        self.assertIsNone(report['sources']); self.assertIsNone(report['graph']); self.assertEqual(report['stages'], [])
        self.assertTrue(all(r['contribution'] is None for r in report['explanations']))
        self.assertEqual(report['riskScore'],result['riskScore'])
        self.assertTrue(any('不是患者摘要' in text for text in report['limitations']))

    def test_blocked_output_has_no_score_graph_path_or_fabricated_stages(self):
        request, _ = pair(); request['visits'] = []
        result = run_workflow(request, score_java_synthetic_payload)
        report = build_course_report(request,result)
        self.assertFalse(report['predictionAvailable']); self.assertIsNone(report['riskScore'])
        self.assertEqual(report['riskLevel'],'UNAVAILABLE'); self.assertEqual(report['explanations'], [])
        self.assertEqual(len(report['stages']),1)
        self.assertIn('不可用（质量阻断）',render_course_html(request,result))

    def test_unsupported_window_block_is_still_reportable_with_original_window(self):
        request, _ = pair(); request['predictionWindowMonths']=12
        report=build_course_report(request,run_workflow(request,score_java_synthetic_payload))
        self.assertEqual(report['status'],'BLOCKED'); self.assertEqual(report['predictionWindowMonths'],12)

    def test_invalid_identity_and_scope_are_refused(self):
        for field,value in [('runId','run-other'),('dataVersion','demo-other'),('dataSource','REAL_RETROSPECTIVE_RESEARCH'),('reviewRequired',False)]:
            request,result=pair(); result[field]=value
            with self.assertRaises(CourseReportError): build_course_report(request,result)

    def test_real_subject_and_research_dto_not_accepted_as_course_report(self):
        request,result=pair(); request['subjectCode']='ACTUAL-REAL-ALIAS'
        with self.assertRaises(CourseReportError): build_course_report(request,result)
        with self.assertRaises(CourseReportError): build_course_report({'input_mode':'REAL_RETROSPECTIVE_RESEARCH'}, {'status':'COMPLETED','result':{}})

    def test_failed_pending_and_fabricated_success_refused(self):
        for status in ('FAILED','PENDING','CANCELLED'):
            request,result=pair(); result['status']=status
            with self.assertRaises(CourseReportError): build_course_report(request,result)
        request,result=pair(); request['visits']=[]
        with self.assertRaises(CourseReportError): build_course_report(request,result)

    def test_finite_score_and_contribution_reconstruction_required(self):
        for value in (None,float('nan'),float('inf'),.01):
            request,result=pair(); result['riskScore']=value
            with self.assertRaises(CourseReportError): build_course_report(request,result)
        request,result=pair(); result['explanations'][0]['contribution']+=.1
        with self.assertRaises(CourseReportError): build_course_report(request,result)

    def test_negative_duration_and_unexpected_top_level_fields_rejected(self):
        request,result=pair(); result['stages'][0]['durationMs']=-1
        with self.assertRaises(CourseReportError): build_course_report(request,result)
        request,result=pair(); result['unwantedSecret']='MUST_NOT_COPY'
        with self.assertRaises(CourseReportError): build_course_report(request,result)

    def test_unrecognized_stage_summary_metadata_is_not_copied(self):
        request,result=pair(); result['stages'][1]['summary']['unwantedSecret']='MUST_NOT_COPY'
        self.assertNotIn('MUST_NOT_COPY',json.dumps(build_course_report(request,result)))

    def test_html_escapes_untrusted_source_code_warnings_and_limitations(self):
        request,result=pair(); request['visits'][0]['visitCode']='<script>alert(1)</script>'
        result['limitations'].append('<img src=x onerror=alert(1)>')
        html=render_course_html(request,result)
        self.assertNotIn('<script>',html);self.assertNotIn('<img src=x',html)
        self.assertIn('&lt;script&gt;',html);self.assertIn('&lt;img',html)

    def test_null_and_zero_source_values_are_not_merged_or_rounded(self):
        request,_=pair(); request['visits'][0]['mmse']=None; request['visits'][-1]['mmse']=0
        request['visits'][-1]['moca']=22.123456
        result=run_workflow(request,score_java_synthetic_payload); report=build_course_report(request,result)
        self.assertIsNone(report['sources']['visits'][0]['mmse']);self.assertEqual(report['sources']['visits'][-1]['mmse'],0)
        self.assertEqual(report['sources']['visits'][-1]['moca'],22.123456)

    def test_digest_binds_each_input_but_not_json_key_order(self):
        request,result=pair(); a=build_course_report(request,result)
        b=build_course_report(dict(reversed(list(request.items()))),dict(reversed(list(result.items()))))
        self.assertEqual(a,b)
        result['stages'][0]['durationMs']=1
        c=build_course_report(request,result)
        self.assertEqual(a['requestSha256'],c['requestSha256']);self.assertNotEqual(a['resultSha256'],c['resultSha256'])

    def test_output_objects_are_independent(self):
        request,result=pair(); report=build_course_report(request,result)
        report['sources']['visits'][0]['mmse']=-1
        self.assertEqual(request['visits'][0]['mmse'],28)
        self.assertEqual(build_course_report(request,result)['sources']['visits'][0]['mmse'],28)

    def test_report_always_keeps_explicit_scientific_boundaries(self):
        request,result=pair(); report=build_course_report(request,result)
        for field in ('sourceAuthenticityVerified','clinicalValidityEstablished','causalEffectIdentified'):self.assertIs(report[field],False)
        self.assertTrue(report['reviewRequired']);self.assertIn('非诊疗报告',render_course_html(request,result))

    def test_audience_and_external_stylesheets_refused(self):
        request,result=pair()
        for audience in ('patient','REAL',[],None):
            with self.assertRaises(CourseReportError): build_course_report(request,result,audience=audience)
        for href in ('https://external.test/style.css','data:text/css,x','/unknown.css'):
            with self.assertRaises(CourseReportError): render_course_html(request,result,stylesheet_href=href)

    def test_same_origin_stylesheet_preserves_existing_csp(self):
        request,result=pair(); html=render_course_html(request,result,stylesheet_href='/api/system/reports/report.css')
        self.assertIn('<link rel="stylesheet" href="/api/system/reports/report.css">',html)
        self.assertNotIn('<style>',html);self.assertNotIn('<script',html)

    def test_bounded_report_rejects_oversize_without_echoing_input(self):
        request,result=pair(); result['limitations'].append('SENSITIVE_'*40000)
        with self.assertRaises(CourseReportError) as context: build_course_report(request,result)
        self.assertEqual(str(context.exception),'REPORT_SIZE')

    def test_all_100_shipped_requests_produce_same_score_as_supplied_course_result(self):
        requests=json.loads((ROOT/'fixtures/synthetic_subjects_100.json').read_text(encoding='utf-8'))['subjects']
        for request in requests:
            result=run_workflow(request,score_java_synthetic_payload);report=build_course_report(request,result)
            self.assertEqual(report['riskScore'],result['riskScore']);self.assertEqual(report['qualityStatus'],result['qualityStatus'])

    def test_cli_writes_only_explicit_new_target_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'report.json'
            command=[sys.executable,'-B','-m','python_service.course_report','--request','contracts/examples/deepagent-v1.request.example.json','--result','contracts/examples/deepagent-v1.response.example.json','--output',str(output),'--format','json']
            run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(run.returncode,0);self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['riskScore'],.8304)
            original=output.read_bytes();run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(run.returncode,0);self.assertEqual(output.read_bytes(),original)

    def test_cli_invalid_pair_creates_no_file_and_does_not_print_source(self):
        with tempfile.TemporaryDirectory() as folder:
            request=Path(folder)/'private.json'; request.write_text('{"secret":"NO_ECHO"}',encoding='utf-8')
            output=Path(folder)/'never.html'
            run=subprocess.run([sys.executable,'-B','-m','python_service.course_report','--request',str(request),'--result','contracts/examples/deepagent-v1.response.example.json','--output',str(output)],cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(run.returncode,0);self.assertFalse(output.exists());self.assertNotIn('NO_ECHO',run.stdout+run.stderr)
