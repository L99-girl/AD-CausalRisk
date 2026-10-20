from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from python_service.demo_course_report_adapter import serve_course_report, enhance_course_report_asset, example_pair, PATH
from python_service.demo_report_adapter import ReportRequestError


class CourseReportAdapterTests(unittest.TestCase):
    def setUp(self):
        self.replies=[]
        self.handler=SimpleNamespace(reply=lambda *args,**kwargs:self.replies.append((args,kwargs)))

    def test_existing_routes_are_not_intercepted(self):
        for route in ('/api/agent/v1/runs','/api/system/reports/synthetic/wb2-test','/api/workbench/v4/status'):
            self.assertFalse(serve_course_report(self.handler,urlsplit(route)))
        self.assertEqual(self.replies,[])

    def test_static_example_json_is_explicitly_not_a_live_task(self):
        self.assertTrue(serve_course_report(self.handler,urlsplit(PATH+'?format=json')))
        value=self.replies[0][0][0]
        self.assertEqual(value['reportOrigin'],'PINNED_CONTRACT_EXAMPLE_NOT_LIVE_RUN')
        self.assertIs(value['liveServiceProbed'],False);self.assertEqual(value['riskScore'],.8304)

    def test_html_has_same_origin_css_and_static_scope_notice(self):
        serve_course_report(self.handler,urlsplit(PATH))
        html=self.replies[0][0][0].decode('utf-8')
        self.assertIn('原契约静态构造示例，非当前运行任务',html)
        self.assertIn('/api/system/reports/report.css',html);self.assertNotIn('<style>',html)

    def test_teaching_does_not_expose_request_sources(self):
        serve_course_report(self.handler,urlsplit(PATH+'?format=json&audience=teaching'))
        self.assertIsNone(self.replies[0][0][0]['sources'])

    def test_post_and_unknown_duplicate_blank_or_long_query_are_rejected_before_read(self):
        variants=[('',True),('?taskId=x',False),('?audience=research&audience=teaching',False),('?format=',False),('?format=json&x=1&y=2',False)]
        for query,write in variants:
            with patch('python_service.demo_course_report_adapter.example_pair',side_effect=AssertionError('READ')):
                with self.assertRaises(ReportRequestError): serve_course_report(self.handler,urlsplit(PATH+query),write=write)
        self.assertEqual(self.replies,[])

    def test_changed_example_refused_without_rendering_or_model_fallback(self):
        with patch('python_service.demo_course_report_adapter.PINS',{'deepagent-v1.request.example.json':'0'*64}):
            with self.assertRaises(ReportRequestError) as error: example_pair()
            self.assertEqual(error.exception.status,503);self.assertEqual(error.exception.code,'COURSE_EXAMPLE_CHANGED')

    def test_missing_examples_fail_explicitly(self):
        with patch('python_service.demo_course_report_adapter.EXAMPLES',Path('NOT-A-REAL-EXAMPLE-DIRECTORY')):
            with self.assertRaises(ReportRequestError) as error: example_pair()
            self.assertEqual(error.exception.code,'COURSE_EXAMPLE_UNAVAILABLE')

    def test_asset_preserves_form_and_uses_accessible_external_tab_links(self):
        original='<section id="course-csv-preview"><form></form></section>'
        html=enhance_course_report_asset('index.html',original)
        self.assertIn(original,html);self.assertIn('aria-labelledby="course-report-title"',html)
        self.assertIn('rel="noopener"',html);self.assertIn('不启动8091',html)
        self.assertEqual(enhance_course_report_asset('app.js','unchanged'),'unchanged')
        for content in ('',original+original):
            with self.assertRaises(ReportRequestError): enhance_course_report_asset('index.html',content)
