from types import SimpleNamespace
import unittest
from urllib.parse import urlsplit
from python_service.demo_timeline_adapter import serve_timeline, TimelineRequestError, PREFIX


class TimelineAdapterTests(unittest.TestCase):
    def setUp(self):
        self.reads=[];self.replies=[];self.bound=True
        def verify():
            if not self.bound:raise ValueError('CONSTRUCTED_BINDING_CHANGED')
        def report(identifier,trace):
            self.reads.append(identifier)
            if identifier=='OAS2_9999':raise KeyError('not found')
            return {'data_version':'constructed','subject':{'visits':[{'visit':1,'days_from_first_mri':0,'mmse':27,'cdr':.5,'nwbv':.7}]}}
        store=SimpleNamespace(source_blobs=verify,report=report)
        self.handler=SimpleNamespace(server=SimpleNamespace(public_components=object(),binding=SimpleNamespace(verify=verify),store=store),reply=self.replies.append)

    def test_public_metric_returns_observation_only(self):
        self.assertTrue(serve_timeline(self.handler,urlsplit(PREFIX+'OAS2_0001?metric=nwbv')))
        self.assertEqual(self.replies[0]['series']['points'][0]['value'],.7)
        self.assertFalse(self.replies[0]['prediction_available'])

    def test_real_alias_arbitrary_fields_and_bad_queries_never_read_public_record(self):
        for suffix in ('ADNI-R-PRIVATE','OAS2_0001?metric=mmse&metric=cdr','OAS2_0001?private=x','OAS2_0001?metric=risk','OAS2_0001?metric='):
            with self.assertRaises(TimelineRequestError):serve_timeline(self.handler,urlsplit(PREFIX+suffix))
        self.assertEqual(self.reads,[])

    def test_source_binding_failure_blocks_read(self):
        self.bound=False
        with self.assertRaises(ValueError):serve_timeline(self.handler,urlsplit(PREFIX+'OAS2_0001'))
        self.assertEqual(self.reads,[])

    def test_unknown_public_subject_is_404(self):
        with self.assertRaises(TimelineRequestError) as error:serve_timeline(self.handler,urlsplit(PREFIX+'OAS2_9999'))
        self.assertEqual(error.exception.status,404)

    def test_old_routes_and_writes_are_left_to_original_handlers(self):
        self.assertFalse(serve_timeline(self.handler,urlsplit('/api/workbench/v1/subjects/OAS2_0001')))
        self.assertFalse(serve_timeline(self.handler,urlsplit(PREFIX+'OAS2_0001'),write=True))
        self.assertEqual(self.reads,[])


if __name__=='__main__':unittest.main()
