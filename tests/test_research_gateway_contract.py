"""Optional research descriptions/entry point, independent of private model files."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from jsonschema import Draft202012Validator,FormatChecker
from openapi_spec_validator import validate

ROOT=Path(__file__).resolve().parents[1]

class ResearchContractTests(unittest.TestCase):
    def test_optional_openapi_valid_and_disjoint_from_course_routes(self):
        spec=json.loads((ROOT/'contracts/research-runtime.openapi.json').read_text(encoding='utf-8'))
        validate(spec)
        old=json.loads((ROOT/'contracts/python-agent.openapi.json').read_text(encoding='utf-8'))
        self.assertFalse(set(spec['paths']) & set(old['paths']))
        self.assertEqual(len(spec['paths']),2)
        self.assertEqual(spec['security'],[{'LocalBearer':[]}])
    def test_synthetic_example_and_declared_versions_match(self):
        spec=json.loads((ROOT/'contracts/research-runtime.openapi.json').read_text(encoding='utf-8'))
        body=json.loads((ROOT/'contracts/examples/research-runtime.request.example.json').read_text(encoding='utf-8'))
        schema={'$ref':'#/components/schemas/ResearchEnvelope','components':spec['components']}
        validator=Draft202012Validator(schema,format_checker=FormatChecker());validator.validate(body)
        with self.assertRaises(Exception):validator.validate({**body,'inputMode':'RESEARCH_RECORD'})
        with self.assertRaises(Exception):validator.validate({**body,'RID':'12345'})
    def test_missing_research_workspace_fails_without_demo_fallback(self):
        run=subprocess.run([sys.executable,'-B','research_gateway.py','--research-workspace',str(ROOT/'not-a-research-workspace')],
                           cwd=ROOT,capture_output=True,text=True)
        self.assertNotEqual(run.returncode,0)
        self.assertIn('research workspace/runtime is unavailable',run.stderr)

if __name__=='__main__':unittest.main()
