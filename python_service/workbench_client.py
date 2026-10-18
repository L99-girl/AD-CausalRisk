"""Controlled local client for the existing retrospective workbench, not a server.

No estimators, clinical tables or private workspace imports are required here.
Results stay in caller memory; the command line prints capability counts only.
"""
from __future__ import annotations

import argparse
import http.client
from http.cookies import SimpleCookie, CookieError
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlsplit

PREFIX = '/api/workbench/v4/'
CONTRACT = 'adni-v8-real-retrospective-batch-v1'
MODE = 'REAL_RETROSPECTIVE_RESEARCH'
MODEL = 'adni-v8-final-materialized-2026-10-11'
COOKIE = 'adcr_research_session'
MAX_RESPONSE = 4 * 1024 * 1024
STATES = {'READY', 'BLOCKED_INPUT', 'RECORDED_RULES_NOT_MET', 'NOT_PROJECTED_LIMIT'}
TERMINAL = {'COMPLETED', 'PARTIAL', 'FAILED', 'CANCELLED'}
FAMILIES = {'age_years', 'education_years', 'mmse', 'cdr_sb', 'cdr_global'}


class ClientError(RuntimeError):
    """Safe diagnostics: never include an HTTP body, alias, credential or score."""
    def __init__(self, code, http_status=None, *, request_outcome_unknown=False):
        self.code = code
        self.http_status = http_status
        self.request_outcome_unknown = request_outcome_unknown
        super().__init__(code)


def require(condition, code='RESPONSE_CONTRACT_MISMATCH'):
    if not condition:
        raise ClientError(code)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def alias_valid(value):
    return isinstance(value, str) and re.fullmatch(r'ADNI-R-[A-Za-z0-9_-]{1,60}', value) is not None


def decode_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'INVALID_RESPONSE_JSON')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ClientError('INVALID_RESPONSE_JSON')
    def finite_float(value):
        parsed = float(value)
        require(math.isfinite(parsed), 'INVALID_RESPONSE_JSON')
        return parsed
    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant, parse_float=finite_float)
        require(isinstance(result, dict), 'INVALID_RESPONSE_JSON')
        return result
    except (UnicodeError, ValueError, RecursionError):
        raise ClientError('INVALID_RESPONSE_JSON') from None


def validate_result(data, alias):
    """Check identity, probability/attribution arithmetic and research boundaries."""
    try:
        require(data['contract'] == CONTRACT and data['computation_contract'] == 'adni-v8-real-retrospective-v1')
        require(data['mode'] == MODE and data['alias'] == alias)
        require(data['historical_realtime_prediction_available'] is False and data['clinical_use_established'] is False)
        require(data['export_allowed'] is False and data['qualification']['out_of_sample'] is None)
        require(isinstance(data['availability'], dict) and bool(data['availability']) and all(value is None for value in data['availability'].values()))
        core = data['core']
        require(core['contractVersion'] == 'adni-v8-research-v1' and core['modelVersion'] == MODEL)
        require(core['caseCode'] == 'LOCAL-REAL-' + alias and core['variant'] == 'trajectory_graph')
        require(core['status'] == 'RESEARCH_COMPUTATION_COMPLETE' and core['scope'] == 'LOCAL_RESEARCH_ONLY')
        require(core['predictionWindowMonths'] == 24 and type(core['predictionWindowMonths']) is int)
        require(core['clinicalUseEstablished'] is False)
        ad, competing = core['adCumulativeIncidence'], core['otherDementiaCumulativeIncidence']
        require(number(ad) and number(competing) and 0 <= ad <= 1 and 0 <= competing <= 1 and ad + competing <= 1 + 1e-12)
        explanation = core['explanation']
        require(explanation['reference'] == 'source_withdrawal_with_derived_features_and_masks_recomputed')
        require(explanation['causalEffectIdentified'] is False)
        contributions = explanation['contributions']
        require(isinstance(contributions, list) and len(contributions) == 5)
        require({item['sourceFamily'] for item in contributions} == FAMILIES)
        require(number(explanation['baseline']) and 0 <= explanation['baseline'] <= 1)
        require(all(number(item['contribution']) for item in contributions))
        require(number(explanation['reconstructionResidual']) and abs(explanation['reconstructionResidual']) <= 1e-12)
        require(abs(explanation['baseline'] + sum(item['contribution'] for item in contributions) - ad) <= 1e-12)
        return data
    except (KeyError, TypeError, AttributeError):
        raise ClientError('RESPONSE_CONTRACT_MISMATCH') from None


class WorkbenchClient:
    """One local authenticated session; use one instance per caller, not threads."""
    def __init__(self, base_url='http://127.0.0.1:8084', *, timeout=15):
        require(isinstance(base_url, str) and re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}/?', base_url) is not None, 'LOOPBACK_URL_REQUIRED')
        parsed = urlsplit(base_url)
        try:
            self.port = parsed.port
            require(1 <= self.port <= 65535, 'LOOPBACK_URL_REQUIRED')
        except ValueError:
            raise ClientError('LOOPBACK_URL_REQUIRED') from None
        require(number(timeout) and 0 < timeout <= 120, 'INVALID_TIMEOUT')
        self.base_url = f'http://127.0.0.1:{self.port}'
        self.timeout = timeout
        self._cookie = None
        self._jobs = {}

    def __repr__(self):
        return '<WorkbenchClient local research session>'

    @property
    def authenticated(self):
        return self._cookie is not None

    def _forget(self):
        self._cookie = None
        self._jobs.clear()

    def _request(self, route, body=None, *, private=False, timeout=None):
        require(not private or self.authenticated, 'SESSION_REQUIRED')
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=self.timeout if timeout is None else timeout)
        headers = {'Accept': 'application/json'}
        if self._cookie:
            headers['Cookie'] = self._cookie
        if body is not None:
            headers.update({'Origin': self.base_url, 'Content-Type': 'application/json'})
        try:
            payload = json.dumps(body, allow_nan=False).encode('utf-8') if body is not None else None
            connection.request('POST' if body is not None else 'GET', PREFIX + route, payload, headers)
            response = connection.getresponse()
            # Do not follow redirects, use configured proxies or forward credentials.
            require(not 300 <= response.status < 400, 'REDIRECT_REFUSED')
            if response.status == 401:
                self._forget()
            require(response.getheader('Content-Type', '').split(';')[0].strip().lower() == 'application/json', 'RESPONSE_MEDIA_TYPE')
            raw = response.read(MAX_RESPONSE + 1)
            require(len(raw) <= MAX_RESPONSE, 'RESPONSE_TOO_LARGE')
            data = decode_json(raw)
            if response.status not in (200, 202):
                code = data.get('code')
                if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', code):
                    code = 'REMOTE_REJECTED'
                raise ClientError(code, response.status)
            return data, response.getheaders()
        except (OSError, http.client.HTTPException):
            raise ClientError('LOCAL_TRANSPORT_FAILED', request_outcome_unknown=body is not None) from None
        finally:
            connection.close()

    def status(self):
        data, _ = self._request('status')
        require(data.get('application_id') == 'ad-causalrisk-system' and data.get('contract') == CONTRACT and data.get('mode') == MODE)
        require(data.get('model_version') == MODEL and data.get('maximum_batch_size') == 10)
        require(data.get('clinical_use_established') is False and data.get('historical_realtime_prediction_available') is False)
        require(data.get('arbitrary_patient_upload_allowed') is False and data.get('export_allowed') is False)
        return data

    def health(self):
        data, _ = self._request('health')
        require(data.get('application_id') == 'ad-causalrisk-system' and data.get('status') == 'ready')
        require(isinstance(data.get('checks'), dict) and bool(data['checks']) and all(value is True for value in data['checks'].values()))
        require(all(type(data.get(name)) is int and data[name] == 0 for name in ('models_deserialized', 'clinical_tables_parsed', 'new_fits')))
        return data

    def login(self, access_code):
        require(not self.authenticated, 'SESSION_ALREADY_OPEN')
        require(isinstance(access_code, str) and 1 <= len(access_code) <= 256 and not re.search(r'[\s;\r\n]', access_code), 'INVALID_ACCESS_CODE')
        self.status()  # Verify the expected research service before sending a credential.
        data, headers = self._request('session', {'access_code': access_code})
        try:
            values = [value for name, value in headers if name.lower() == 'set-cookie']
            require(len(values) == 1 and data.get('authenticated') is True)
            cookie = SimpleCookie(); cookie.load(values[0])
            require(set(cookie) == {COOKIE} and cookie[COOKIE]['path'] == PREFIX and bool(cookie[COOKIE]['httponly']))
            token = cookie[COOKIE].value
            require(re.fullmatch(r'[A-Za-z0-9_-]{24,128}', token) is not None)
            self._cookie = f'{COOKIE}={token}'
            return {'authenticated': True, 'expires_in_seconds': data['expires_in_seconds']}
        except (CookieError, KeyError):
            raise ClientError('RESPONSE_CONTRACT_MISMATCH') from None

    def login_file(self, access_code_file):
        try:
            with Path(access_code_file).open('r', encoding='ascii') as stream:
                code = stream.read(258).strip()
        except (OSError, UnicodeError):
            raise ClientError('ACCESS_CODE_FILE_UNAVAILABLE') from None
        return self.login(code)

    def logout(self):
        try:
            if self.authenticated:
                data, _ = self._request('logout', {}, private=True)
                require(data.get('authenticated') is False)
        finally:
            self._forget()

    def __enter__(self):
        return self

    def __exit__(self, error_type, error, traceback):
        try:
            self.logout()
        except ClientError:
            if error is None:
                raise
        return False

    def cases(self, *, page=1, page_size=20, state='READY', query=''):
        require(integer(page, 1) and page <= 100000 and integer(page_size, 1) and page_size <= 100, 'INVALID_PAGINATION')
        require(isinstance(state, str) and state in STATES | {'ALL'}, 'INVALID_FILTER')
        require(isinstance(query, str) and len(query) <= 80, 'INVALID_FILTER')
        data, _ = self._request('real/cases?' + urlencode({'page': page, 'page_size': page_size, 'state': state, 'q': query}), private=True)
        try:
            require(data['page'] == page and data['page_size'] == page_size)
            require(all(integer(data[name]) for name in ('total', 'registry_total', 'projected_total', 'ready_total')))
            require(isinstance(data['items'], list) and len(data['items']) <= page_size)
            require(len(data['items']) <= data['total'] <= data['registry_total'])
            require(data['ready_total'] <= data['projected_total'] <= data['registry_total'])
            require(all(alias_valid(row['alias']) and row['state'] in STATES for row in data['items']))
            require(len({row['alias'] for row in data['items']}) == len(data['items']))
            require(state == 'ALL' or all(row['state'] == state for row in data['items']))
            return data
        except (KeyError, TypeError):
            raise ClientError('RESPONSE_CONTRACT_MISMATCH') from None

    def _job(self, job, *, identifier=None, aliases=None):
        try:
            require(isinstance(job['id'], str) and re.fullmatch(r'wb4-[a-f0-9]{32}', job['id']) is not None)
            require(identifier is None or job['id'] == identifier)
            require(job['mode'] == MODE and job['result_persistence'] is False)
            require(job['status'] in TERMINAL | {'PENDING', 'RUNNING'})
            require(integer(job['total'], 1) and job['total'] <= 10 and integer(job['processed']) and job['processed'] <= job['total'])
            require(isinstance(job['cases'], list) and len(job['cases']) == job['total'])
            names = [row['alias'] for row in job['cases']]
            require(all(alias_valid(name) for name in names) and len(set(names)) == len(names))
            require(aliases is None or names == list(aliases))
            require(all(row['status'] in {'PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'DISCARDED', 'CANCELLED'} for row in job['cases']))
            if job['status'] == 'COMPLETED':
                require(job['processed'] == job['total'] and all(row['status'] == 'COMPLETED' for row in job['cases']))
            elif job['status'] in {'FAILED', 'PARTIAL'}:
                require(job['processed'] == job['total'] and all(row['status'] in {'COMPLETED', 'FAILED'} for row in job['cases']))
                successes = sum(row['status'] == 'COMPLETED' for row in job['cases'])
                require(successes == 0 if job['status'] == 'FAILED' else 0 < successes < job['total'])
            elif job['status'] == 'CANCELLED':
                require(all(row['status'] in {'DISCARDED', 'CANCELLED'} for row in job['cases']))
            return job
        except (KeyError, TypeError):
            raise ClientError('RESPONSE_CONTRACT_MISMATCH') from None

    def submit(self, aliases, *, request_key):
        require(isinstance(aliases, list) and 1 <= len(aliases) <= 10 and all(alias_valid(alias) for alias in aliases), 'INVALID_BATCH')
        require(len(set(aliases)) == len(aliases), 'INVALID_BATCH')
        require(isinstance(request_key, str) and re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_key) is not None, 'INVALID_REQUEST_KEY')
        data, _ = self._request('jobs', {'request_key': request_key, 'aliases': aliases, 'mode': MODE}, private=True)
        try:
            job = self._job(data['job'], aliases=aliases)
            require(job['request_key'] == request_key and type(data['idempotent_replay']) is bool)
            self._jobs[job['id']] = tuple(aliases)
            return data
        except KeyError:
            raise ClientError('RESPONSE_CONTRACT_MISMATCH') from None

    def job(self, identifier, *, _timeout=None):
        require(isinstance(identifier, str) and identifier in self._jobs, 'UNKNOWN_CLIENT_JOB')
        data, _ = self._request('jobs/' + identifier, private=True, timeout=_timeout)
        try:
            return self._job(data['job'], identifier=identifier, aliases=self._jobs[identifier])
        except KeyError:
            raise ClientError('RESPONSE_CONTRACT_MISMATCH') from None

    def wait(self, identifier, *, timeout=90, poll_interval=.25):
        require(number(timeout) and timeout > 0 and number(poll_interval) and poll_interval > 0, 'INVALID_TIMEOUT')
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'WAIT_TIMEOUT')
            job = self.job(identifier, _timeout=min(self.timeout, remaining))
            if job['status'] in TERMINAL:
                return job
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))

    def cancel(self, identifier):
        require(isinstance(identifier, str) and identifier in self._jobs, 'UNKNOWN_CLIENT_JOB')
        data, _ = self._request('jobs/' + identifier + '/cancel', {}, private=True)
        try:
            job = self._job(data['job'], identifier=identifier, aliases=self._jobs[identifier])
            require(job['status'] == 'CANCELLED')
            return job
        except KeyError:
            raise ClientError('RESPONSE_CONTRACT_MISMATCH') from None

    def result(self, identifier, alias):
        require(isinstance(identifier, str) and identifier in self._jobs and alias in self._jobs[identifier], 'RESULT_NOT_REQUESTED')
        data, _ = self._request('jobs/' + identifier + '/results/' + alias, private=True)
        return validate_result(data, alias)


def main():
    parser = argparse.ArgumentParser(description='Check the existing local research service; never print individual results.')
    parser.add_argument('--url', default='http://127.0.0.1:8084')
    parser.add_argument('--access-code-file', type=Path)
    args = parser.parse_args()
    try:
        with WorkbenchClient(args.url) as client:
            client.status()
            client.health()
            report = {'status': 'ready', 'contract': CONTRACT, 'mode': MODE, 'clinical_use_established': False}
            if args.access_code_file:
                client.login_file(args.access_code_file)
                catalog = client.cases(page_size=1)
                report.update(registry_total=catalog['registry_total'], ready_total=catalog['ready_total'])
        print(json.dumps(report))
        return 0
    except ClientError as error:
        print(json.dumps({'status': 'not_ready', 'code': error.code, 'http_status': error.http_status}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
