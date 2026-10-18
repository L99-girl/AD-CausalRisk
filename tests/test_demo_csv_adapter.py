from types import SimpleNamespace
from urllib.parse import urlsplit
from email.message import Message
import unittest
from python_service.demo_csv_adapter import serve_course_csv, enhance_csv_asset, PATH
from python_service.course_csv import CsvPreviewError
from test_course_csv import sample


class Handler:
    def __init__(self):
        self.server=SimpleNamespace(server_port=8084)
        self.headers=Message();self.headers['Origin']='http://127.0.0.1:8084'
        self.body=sample();self.result=None;self.reads=0
    def read_course_csv_json(self):self.reads+=1;return self.body
    def reply(self,value):self.result=value


class CsvAdapterTests(unittest.TestCase):
    def test_unrelated_path_untouched_and_no_reads(self):
        handler=Handler();self.assertFalse(serve_course_csv(handler,urlsplit('/api/agent/v1/runs'),write=True))
        self.assertEqual(handler.reads,0);self.assertIsNone(handler.result)

    def test_only_post_without_query(self):
        for target,write,code in [(PATH,False,'POST_REQUIRED'),(PATH+'?x=1',True,'QUERY')]:
            handler=Handler()
            with self.assertRaises(CsvPreviewError) as error:serve_course_csv(handler,urlsplit(target),write=write)
            self.assertEqual(error.exception.code,code);self.assertEqual(handler.reads,0)

    def test_origin_missing_duplicate_or_foreign_rejected_before_body(self):
        for origins in ([],['http://external.test'],['http://127.0.0.1:8084']*2):
            handler=Handler();del handler.headers['Origin']
            for origin in origins:handler.headers['Origin']=origin
            with self.assertRaises(CsvPreviewError):serve_course_csv(handler,urlsplit(PATH),write=True)
            self.assertEqual(handler.reads,0)

    def test_post_responds_only_safe_preview_without_run(self):
        handler=Handler();self.assertTrue(serve_course_csv(handler,urlsplit(PATH),write=True))
        self.assertEqual(handler.reads,1);self.assertEqual(handler.result['qualityCounts']['PASS'],1)
        self.assertFalse(handler.result['modelExecuted']);self.assertNotIn('visits',handler.result)

    def test_no_real_mode(self):
        handler=Handler();handler.body['input_mode']='REAL'
        with self.assertRaises(CsvPreviewError) as error:serve_course_csv(handler,urlsplit(PATH),write=True)
        self.assertEqual(error.exception.code,'SYNTHETIC_ONLY');self.assertIsNone(handler.result)

    def test_asset_requires_unique_anchor_and_leaves_original_form(self):
        original='<section id="import-preview"><form id="csv-form"></form></section>'
        result=enhance_csv_asset('index.html',original)
        self.assertTrue(result.startswith(original));self.assertEqual(result.count('id="course-csv-form"'),1)
        for source in ('',original+original):
            with self.assertRaises(ValueError):enhance_csv_asset('index.html',source)

    def test_ui_uses_escaped_dynamic_values_accessible_errors_and_no_storage(self):
        html=enhance_csv_asset('index.html','<section id="import-preview"></section>')
        js=enhance_csv_asset('app.js','')
        self.assertIn('aria-describedby="course-csv-visits-error"',html)
        self.assertIn('aria-live="polite"',html);self.assertIn('tabindex="-1"',html)
        self.assertIn('escapeHtml(item.code)',js);self.assertIn('escapeHtml(item.subjectCode)',js)
        self.assertIn('request!==courseCsvRequest',js);self.assertIn('.focus()',js)
        self.assertNotIn('localStorage',js);self.assertNotIn('sessionStorage',js)
        self.assertNotIn('/commit',js)
