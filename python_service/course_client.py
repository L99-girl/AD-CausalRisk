"""Standard-library client for the existing synchronous course Agent interface."""
import argparse
import copy
import http.client
import json
import re
from uuid import uuid4
from urllib.parse import urlsplit
from .course_protocol import (CourseContract,CourseProtocolError,decode_json,validate_course_request,
                              validate_course_result,number,utf8_json_media,identity_encoding)
from .deepagent_contract import CONTRACT_VERSION,WORKFLOW_VERSION,MODEL_VERSION,STAGES,RUN_ID_RE,request_identity_digest

MAX_RESPONSE=2*1024*1024
MAX_REQUEST=128*1024
TRACE_RE=re.compile(r'[A-Za-z0-9._-]{1,64}\Z')
# These are the implemented operations' rejection semantics, not just the
# wire schema's unconstrained code string. New peer errors need review.
POST_ERROR_CODES={400:{'VALIDATION_400'},408:{'REQUEST_TIMEOUT'},
                  409:{'AGENT_CONTRACT_MISMATCH','RUN_ID_CONFLICT'},
                  413:{'PAYLOAD_TOO_LARGE'},415:{'UNSUPPORTED_MEDIA_TYPE'},
                  500:{'ASSESSMENT_FAILED'},503:{'RUN_CAPACITY_REACHED'}}
GET_ERROR_CODES={400:{'VALIDATION_400'},404:{'RUN_NOT_FOUND','ROUTE_NOT_FOUND'}}
HEALTH_ERROR_CODES={400:{'VALIDATION_400'},404:{'ROUTE_NOT_FOUND'}}


class CourseClientError(RuntimeError):
    def __init__(self,code,http_status=None,*,request_outcome_unknown=False):
        self.code=code;self.http_status=http_status;self.request_outcome_unknown=request_outcome_unknown
        super().__init__(code)


def require(condition,code):
    if not condition:raise CourseProtocolError(code)


def _trace_id(value):
    value=uuid4().hex if value is None else value
    if not isinstance(value,str) or TRACE_RE.fullmatch(value) is None:
        raise CourseClientError('INVALID_TRACE_ID')
    return value


def _request_snapshot(payload,contract):
    try:
        payload=copy.deepcopy(payload)
        validate_course_request(payload,contract)
        return payload
    except (CourseProtocolError,TypeError,KeyError,ValueError,RecursionError,OverflowError):
        raise CourseClientError('INVALID_REQUEST') from None


def _request_bytes(payload):
    try:
        raw=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    except (TypeError,ValueError,OverflowError,RecursionError):
        raise CourseClientError('INVALID_JSON') from None
    if len(raw)>MAX_REQUEST:raise CourseClientError('REQUEST_TOO_LARGE')
    return raw


class CourseClient:
    """One caller's run/request bindings; no persistent store or implicit retry."""
    def __init__(self,base_url='http://127.0.0.1:8091',*,timeout=15):
        try:
            require(isinstance(base_url,str) and re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}/?',base_url) is not None,'LOOPBACK_URL_REQUIRED')
            port=urlsplit(base_url).port
            require(port is not None and 1<=port<=65535,'LOOPBACK_URL_REQUIRED')
            require(number(timeout) and 0<timeout<=120,'INVALID_TIMEOUT')
            self.contract=CourseContract()
        except (OSError,ValueError,TypeError) as error:
            raise CourseClientError(getattr(error,'code','CONTRACT_LOAD_FAILED')) from None
        self.port=port;self.timeout=timeout;self._requests={};self._ready=False

    def __repr__(self):return '<CourseClient local synthetic session>'

    def _request(self,path,body=None,*,trace_id=None):
        trace_id=_trace_id(trace_id)
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=self.timeout)
        status=None;sent=False;post=body is not None
        try:
            headers={'Accept':'application/json','X-Trace-Id':trace_id}
            # POST bytes are prepared from the entry snapshot before health,
            # binding or network I/O. Never re-read a caller's live object.
            raw=body
            if post:
                require(len(raw)<=MAX_REQUEST,'REQUEST_TOO_LARGE');headers['Content-Type']='application/json'
            sent=True;connection.request('POST' if post else 'GET',path,body=raw,headers=headers)
            response=connection.getresponse();status=response.status
            require(not 300<=status<400,'REDIRECT_REFUSED')
            require(utf8_json_media(response.headers),'RESPONSE_MEDIA_TYPE')
            lengths=response.headers.get_all('Content-Length',[])
            require(len(lengths)==1 and re.fullmatch(r'[0-9]{1,12}',lengths[0]) is not None,'RESPONSE_FRAMING')
            require(int(lengths[0])<=MAX_RESPONSE and not response.headers.get_all('Transfer-Encoding',[]),'RESPONSE_TOO_LARGE')
            require(identity_encoding(response.headers),'RESPONSE_ENCODING')
            raw=response.read(MAX_RESPONSE+1)
            require(len(raw)<=MAX_RESPONSE and len(raw)==int(lengths[0]),'RESPONSE_LENGTH')
            data=decode_json(raw)
            require(response.headers.get_all('X-Trace-Id')==[trace_id],'RESPONSE_TRACE')
            if status!=200:
                codes=POST_ERROR_CODES if post else HEALTH_ERROR_CODES if path=='/api/health' else GET_ERROR_CODES
                require(status in codes,'UNEXPECTED_HTTP_STATUS')
                self.contract.validate('AgentError',data)
                require(data['traceId']==trace_id and re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}',data['code']) is not None
                        and data['code'] in codes[status],'ERROR_CONTRACT')
                raise CourseClientError(data['code'],status)
            return data
        except CourseClientError:raise
        except CourseProtocolError as error:raise CourseClientError(error.code,status,request_outcome_unknown=post and sent) from None
        except (OSError,TimeoutError,http.client.HTTPException):raise CourseClientError('LOCAL_TRANSPORT_FAILED',status,request_outcome_unknown=post and sent) from None
        except (TypeError,ValueError,OverflowError):raise CourseClientError('INVALID_JSON',status,request_outcome_unknown=post and sent) from None
        finally:connection.close()

    def health(self):
        self._ready=False;data=self._request('/api/health')
        expected={'status':'ok','serviceMode':'COURSE_SYNTHETIC','httpApiVersion':'course-agent-http-v1',
                  'contractVersion':CONTRACT_VERSION,'workflowVersion':WORKFLOW_VERSION,'modelVersion':MODEL_VERSION,
                  'dataSource':'SYNTHETIC_DEMO','synchronousExecution':True,'persistentRunStore':False,
                  'researchEvidenceLoaded':False,'individualResearchModelDeployed':False,'stages':list(STAGES)}
        if data!=expected or any(type(data.get(key)) is not bool for key in ('synchronousExecution','persistentRunStore','researchEvidenceLoaded','individualResearchModelDeployed')):
            raise CourseClientError('SERVICE_CONTRACT_MISMATCH')
        self._ready=True;return data

    def create(self,payload,*,trace_id=None):
        payload=_request_snapshot(payload,self.contract)
        trace_id=_trace_id(trace_id)
        raw=_request_bytes(payload)
        run_id=payload['runId'];known=self._requests.get(run_id)
        if known is None and len(self._requests)>=1000:raise CourseClientError('CLIENT_BINDING_CAPACITY')
        if not self._ready:self.health()
        if known is None:self._requests[run_id]=copy.deepcopy(payload)
        data=self._request('/api/agent/v1/runs',raw,trace_id=trace_id)
        if known is not None and request_identity_digest(known)!=request_identity_digest(payload):raise CourseClientError('CONFLICTING_RUN_ACCEPTED',200,request_outcome_unknown=True)
        try:return validate_course_result(data,payload,self.contract)
        except CourseProtocolError as error:raise CourseClientError(error.code,200,request_outcome_unknown=True) from None

    def result(self,run_id,*,expected_request=None,trace_id=None):
        if not isinstance(run_id,str) or RUN_ID_RE.fullmatch(run_id) is None:raise CourseClientError('INVALID_RUN_ID')
        payload=self._requests.get(run_id)
        if expected_request is not None:
            expected_request=_request_snapshot(expected_request,self.contract)
            if expected_request['runId']!=run_id or (payload is not None and request_identity_digest(payload)!=request_identity_digest(expected_request)):
                raise CourseClientError('REQUEST_BINDING_MISMATCH')
            payload=expected_request
        if payload is None:raise CourseClientError('REQUEST_BINDING_REQUIRED')
        trace_id=_trace_id(trace_id)
        if not self._ready:self.health()
        data=self._request('/api/agent/v1/runs/'+run_id,trace_id=trace_id)
        try:return validate_course_result(data,payload,self.contract)
        except CourseProtocolError as error:raise CourseClientError(error.code,200) from None


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',default='http://127.0.0.1:8091');args=parser.parse_args()
    try:
        data=CourseClient(args.url).health()
        print(json.dumps({key:data[key] for key in ('serviceMode','contractVersion','modelVersion','persistentRunStore','dataSource')}))
    except CourseClientError as error:
        print(json.dumps({'code':error.code,'http_status':error.http_status,'request_outcome_unknown':error.request_outcome_unknown}));return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
