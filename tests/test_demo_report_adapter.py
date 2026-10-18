"""Optional demo adapter checks without the real service or private inputs."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from urllib.parse import urlsplit
from python_service.demo_report_adapter import serve_report, enhance_asset, ReportRequestError, PREFIX

spec = importlib.util.spec_from_file_location('constructed_report_fixture', Path(__file__).with_name('test_research_report.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.task = fixture.task(); self.replies = []; self.events = []; self.reads = []
        self.binding_ok = True
        def verify():
            if not self.binding_ok:raise RuntimeError('CONSTRUCTED_BINDING_CHANGED')
        def get(identifier):
            self.reads.append(identifier); return self.task
        server = SimpleNamespace(public_components=object(), binding=SimpleNamespace(verify=verify),
                                 tasks=SimpleNamespace(get=get), audit=lambda *args:self.events.append(args))
        self.handler = SimpleNamespace(server=server, reply=lambda *args, **kwargs:self.replies.append((args, kwargs)))
        self.url = PREFIX + self.task['id']

    def test_existing_routes_and_post_methods_are_left_to_original_handlers(self):
        self.assertFalse(serve_report(self.handler, urlsplit('/api/workbench/v2/catalog')))
        self.assertFalse(serve_report(self.handler, urlsplit(self.url), write=True))
        self.assertEqual(self.reads, [])

    def test_report_json_and_html_use_only_existing_completed_task(self):
        self.assertTrue(serve_report(self.handler, urlsplit(self.url + '?format=json'), trace='constructed-trace'))
        self.assertEqual(self.replies[-1][0][0]['scope'], 'SYNTHETIC_TEST')
        self.assertTrue(serve_report(self.handler, urlsplit(self.url + '?audience=teaching&format=html')))
        self.assertEqual(self.replies[-1][1]['media'], 'text/html; charset=utf-8')
        self.assertNotIn('合成输入来源', self.replies[-1][0][0].decode())

    def test_bad_queries_and_identifiers_rejected_before_task_read(self):
        for url in (PREFIX + 'ADNI-R-PRIVATE', self.url + '?format=pdf', self.url + '?audience=patient',
                    self.url + '?format=json&format=html', self.url + '?private=x', self.url + '?a=1&b=2&c=3'):
            with self.assertRaises(ReportRequestError):serve_report(self.handler, urlsplit(url))
        self.assertEqual(self.reads, [])

    def test_source_binding_failure_blocks_report_generation(self):
        self.binding_ok = False
        with self.assertRaisesRegex(RuntimeError, 'CONSTRUCTED_BINDING_CHANGED'):
            serve_report(self.handler, urlsplit(self.url))
        self.assertEqual(self.reads, [])

    def test_real_and_unfinished_tasks_have_no_success_reply(self):
        for updates in ({'input_mode': 'REAL_RETROSPECTIVE_RESEARCH'}, {'status': 'FAILED'}):
            self.task = fixture.task(); self.task.update(updates)
            with self.assertRaises(ReportRequestError) as error:serve_report(self.handler, urlsplit(self.url))
            self.assertEqual(error.exception.status, 422)
        self.assertEqual(self.replies, [])
        self.assertEqual(self.events, [])

    def test_report_audit_contains_no_case_or_model_values(self):
        serve_report(self.handler, urlsplit(self.url), trace='constructed-trace')
        self.assertEqual(self.events, [('SYNTHETIC_REPORT_RENDERED', 'constructed-trace')])

    def test_ui_links_and_hiding_do_not_replace_original_download(self):
        html = enhance_asset('index.html', '<a id="download-task" class="button">JSON</a>')
        self.assertIn('id="preview-report"', html); self.assertIn('id="teaching-report"', html)
        self.assertIn('<a id="download-task"', html)
        js = enhance_asset('app.js', "$('cancel-task').hidden=true;$('download-task').hidden=true;\n$('download-task').href=V2+'tasks/'+task.id+'/report';")
        self.assertIn("$('preview-report').hidden=true", js)
        self.assertIn("task.status!=='COMPLETED'", js)
        self.assertIn("V2+'tasks/'+task.id+'/report'", js)

    def test_incompatible_ui_is_detected_instead_of_silently_missing_buttons(self):
        for name in ('index.html', 'app.js'):
            with self.assertRaisesRegex(ReportRequestError, 'REPORT_UI_INCOMPATIBLE'):enhance_asset(name, 'changed')

    def test_served_reports_use_same_origin_styles_under_original_csp(self):
        serve_report(self.handler, urlsplit(self.url))
        html = self.replies[-1][0][0].decode()
        self.assertIn('href="/api/system/reports/report.css"', html)
        self.assertNotIn('<style>', html)
        serve_report(self.handler, urlsplit('/api/system/reports/report.css'))
        self.assertEqual(self.replies[-1][1]['media'], 'text/css; charset=utf-8')
        self.assertIn(b'@media print', self.replies[-1][0][0])


if __name__ == '__main__':unittest.main()
