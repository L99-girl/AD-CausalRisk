"""Real loopback early rejection and failure DTO regressions; synthetic only."""
from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import socket
import threading
import unittest
from python_service.server import AgentServer,RunStore,MAX_BODY

ROOT=Path(__file__).resolve().parents[1]


class CountingStore(RunStore):
    def __init__(self,failure=None):super().__init__();self.calls=0;self.failure=failure
    def create(self,payload):
        self.calls+=1
        if self.failure:
            failure=self.failure;self.failure=None;raise failure('CONSTRUCTED_INTERNAL_DETAIL')
        return super().create(payload)


@contextmanager
def service(store):
    server=AgentServer(('127.0.0.1',0),store);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield server.server_port
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def post(port,body,headers=None,*,half_close=False):
    connection=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
    fields=headers if headers is not None else [('Content-Type','application/json'),('Content-Length',str(len(body)))]
    try:
        connection.putrequest('POST','/api/agent/v1/runs')
        for key,value in [*fields,('X-Trace-Id','transport-test')]:connection.putheader(key,value)
        connection.endheaders(body)
        if half_close:connection.sock.shutdown(socket.SHUT_WR)
        response=connection.getresponse();value=json.loads(response.read())
        return response.status,value,response.getheader('X-Trace-Id')
    finally:connection.close()


class CourseTransportTests(unittest.TestCase):
    def test_repeated_media_and_oversize_rejections_deliver_complete_json_without_execution(self):
        store=CountingStore()
        with service(store) as port:
            for _ in range(3):
                for body,headers,status,code in [(b'invalid-json',[('Content-Type','text/plain'),('Content-Length','12')],415,'UNSUPPORTED_MEDIA_TYPE'),
                                                 (b' '*(MAX_BODY+1),None,413,'PAYLOAD_TOO_LARGE')]:
                    actual,value,trace=post(port,body,headers)
                    self.assertEqual(actual,status);self.assertEqual(value['code'],code)
                    self.assertEqual(value['traceId'],trace)
            self.assertEqual(store.calls,0);self.assertEqual(store.runs,{})

    def test_ambiguous_framing_and_media_never_reach_run_store(self):
        variants=[([('Content-Type','application/json'),('Content-Length','2'),('Content-Length','2')],400),
                  ([('Content-Type','application/json'),('Content-Length','2'),('Transfer-Encoding','chunked')],400),
                  ([('Content-Type','application/json'),('Content-Length','2'),('Transfer-Encoding','')],400),
                  ([('Content-Type','application/json'),('Content-Type','text/plain'),('Content-Length','2')],415)]
        store=CountingStore()
        with service(store) as port:
            for headers,status in variants:self.assertEqual(post(port,b'{}',headers)[0],status)
            self.assertEqual(store.calls,0)

    def test_short_body_with_valid_json_is_still_rejected_for_wrong_declared_length(self):
        store=CountingStore()
        with service(store) as port:
            status,value,_=post(port,b'{}',[('Content-Type','application/json'),('Content-Length','20')],half_close=True)
            self.assertEqual(status,400);self.assertEqual(value['code'],'VALIDATION_400');self.assertEqual(store.calls,0)

    def test_unexpected_runtime_failure_is_safe_500_not_disconnection(self):
        store=CountingStore(RuntimeError)
        body=(ROOT/'contracts/examples/deepagent-v1.request.example.json').read_bytes()
        with service(store) as port:
            status,value,trace=post(port,body)
            self.assertEqual(status,500);self.assertEqual(value['code'],'ASSESSMENT_FAILED')
            self.assertNotIn('CONSTRUCTED_INTERNAL',str(value));self.assertEqual(value['traceId'],trace)
            self.assertEqual(store.runs,{})
            self.assertEqual(post(port,body)[0],200)

    def test_unexpected_computation_valueerror_is_not_misreported_as_bad_json(self):
        store=CountingStore(ValueError)
        with service(store) as port:
            status,value,_=post(port,(ROOT/'contracts/examples/deepagent-v1.request.example.json').read_bytes())
            self.assertEqual(status,500);self.assertEqual(value['code'],'ASSESSMENT_FAILED')

    def test_valid_followup_after_early_rejection_executes_only_the_explicit_new_request(self):
        store=CountingStore();body=(ROOT/'contracts/examples/deepagent-v1.request.example.json').read_bytes()
        with service(store) as port:
            self.assertEqual(post(port,body,[('Content-Type','text/plain'),('Content-Length',str(len(body)))])[0],415)
            self.assertEqual(store.calls,0)
            self.assertEqual(post(port,body)[0],200);self.assertEqual(store.calls,1)


if __name__=='__main__':unittest.main()
