"""Frozen course wire-schema and semantic checks using standard-library code.

Only the keyword subset present in the shipped contract is supported. Future
unknown keywords fail closed. This is not a general JSON Schema implementation.
"""
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re
from .deepagent_contract import (validate_request, AgentContractError, CONTRACT_VERSION,
                                WORKFLOW_VERSION, MODEL_VERSION, STAGES, FEATURES)

CONTRACT_FILE=Path(__file__).resolve().parents[1]/'contracts/python-agent.openapi.json'
FROZEN_CONTRACT_SHA256='90384cccce76dd35c8d31dbcc182d8c2f0ff32031948dc694ca7520cdf13eb6c'
KEYWORDS={'type','properties','required','additionalProperties','items','maxItems','const','enum',
          'format','pattern','minLength','maxLength','minimum','maximum','allOf','if','then','else'}


class CourseProtocolError(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)


def require(condition,code='RESULT_SEMANTICS'):
    if not condition:raise CourseProtocolError(code)


def number(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except OverflowError:return False


def same(a,b):
    if type(a) is bool or type(b) is bool:return type(a) is type(b) and a==b
    return a==b


def json_tree(value,depth=0):
    require(depth<=64,'JSON_DEPTH')
    if isinstance(value,dict):
        require(all(isinstance(key,str) for key in value),'JSON_TYPES')
        for child in value.values():json_tree(child,depth+1)
    elif isinstance(value,list):
        for child in value:json_tree(child,depth+1)
    else:require(value is None or type(value) in (str,bool) or number(value),'JSON_TYPES')


def decode_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'INVALID_RESPONSE_JSON');result[key]=value
        return result
    def constant(_):raise CourseProtocolError('INVALID_RESPONSE_JSON')
    try:
        result=json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
        require(isinstance(result,dict),'INVALID_RESPONSE_JSON');json_tree(result)
        return result
    except (UnicodeError,ValueError,RecursionError):raise CourseProtocolError('INVALID_RESPONSE_JSON') from None


class CourseContract:
    def __init__(self):
        raw=CONTRACT_FILE.read_bytes();document=decode_json(raw)
        require(document['info']['version']=='course-agent-http-v1','CONTRACT_VERSION')
        self.sha256=hashlib.sha256(raw).hexdigest();self.schemas=document['components']['schemas']
        require(self.sha256==FROZEN_CONTRACT_SHA256,'FROZEN_CONTRACT_CHANGED')
        require(set(self.schemas)=={'AgentRequest','AgentResult','AgentError'},'CONTRACT_SCHEMAS')
        for schema in self.schemas.values():self.check_keywords(schema)

    @classmethod
    def check_keywords(cls,schema):
        require(isinstance(schema,dict) and set(schema)<=KEYWORDS,'UNSUPPORTED_SCHEMA_KEYWORD')
        for key,value in schema.items():
            if key=='properties':
                for child in value.values():cls.check_keywords(child)
            elif key in ('items','if','then','else'):cls.check_keywords(value)
            elif key=='allOf':
                for child in value:cls.check_keywords(child)

    def validate(self,name,value):
        json_tree(value)
        require(self.matches(self.schemas[name],value),'WIRE_SCHEMA_MISMATCH')

    @classmethod
    def matches(cls,schema,value):
        types=schema.get('type');types=[types] if isinstance(types,str) else types
        if types:
            checks={'null':value is None,'boolean':type(value) is bool,'string':isinstance(value,str),
                    'number':number(value),'integer':number(value) and float(value).is_integer(),
                    'array':isinstance(value,list),'object':isinstance(value,dict)}
            if not any(checks.get(kind,False) for kind in types):return False
        if 'const' in schema and not same(value,schema['const']):return False
        if 'enum' in schema and not any(same(value,item) for item in schema['enum']):return False
        if isinstance(value,dict):
            properties=schema.get('properties',{})
            if not set(schema.get('required',[]))<=set(value):return False
            if schema.get('additionalProperties') is False and not set(value)<=set(properties):return False
            if not all(cls.matches(child,value[key]) for key,child in properties.items() if key in value):return False
        if isinstance(value,list):
            if len(value)>schema.get('maxItems',len(value)):return False
            if 'items' in schema and not all(cls.matches(schema['items'],item) for item in value):return False
        if isinstance(value,str):
            if not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',len(value)):return False
            if 'pattern' in schema and re.search(schema['pattern'],value) is None:return False
            try:
                if schema.get('format')=='date' and date.fromisoformat(value).isoformat()!=value:return False
                if schema.get('format')=='date-time':
                    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})',value):return False
                    if datetime.fromisoformat(value.replace('Z','+00:00')).utcoffset() is None:return False
            except ValueError:return False
        if number(value) and not schema.get('minimum',value)<=value<=schema.get('maximum',value):return False
        if not all(cls.matches(child,value) for child in schema.get('allOf',[])):return False
        if 'if' in schema:
            branch='then' if cls.matches(schema['if'],value) else 'else'
            if branch in schema and not cls.matches(schema[branch],value):return False
        return True


def validate_course_request(payload,contract):
    contract.validate('AgentRequest',payload)
    try:validate_request(payload)
    except AgentContractError:raise CourseProtocolError('REQUEST_SEMANTICS') from None


def context(payload):
    visits=sorted(payload['visits'],key=lambda row:(row['visitDate'],row['visitCode']))
    latest=visits[-1] if visits else None;index=latest['visitDate'] if latest else None
    eligible=[row for row in payload['features'] if index and row['recordedAt']<=index]
    features={};seen={};conflict=False
    for row in sorted(eligible,key=lambda row:row['recordedAt']):
        key=(row['featureName'],row['recordedAt'])
        if key in seen and seen[key]!=row.get('featureValue'):conflict=True
        seen[key]=row.get('featureValue')
        if row.get('featureValue') is not None:features[row['featureName']]=row
    cognition=latest is not None and any(latest.get(key) is not None for key in ('mmse','moca','cdrSb'))
    blocked=not cognition or sum(row['visitDate']==index for row in visits)>1 or conflict or payload['predictionWindowMonths']!=24
    return visits,latest,index,features,eligible,blocked


def validate_course_result(result,payload,contract):
    try:return _validate_course_result(result,payload,contract)
    except (KeyError,TypeError,AttributeError,OverflowError,RecursionError):
        raise CourseProtocolError('RESULT_STRUCTURE') from None


def _validate_course_result(result,payload,contract):
    validate_course_request(payload,contract);contract.validate('AgentResult',result)
    require(all(result[key]==payload[key] for key in ('runId','dataVersion','modelVersion','contractVersion')),'RESULT_IDENTITY')
    require(result['workflowVersion']==WORKFLOW_VERSION and result['dataSource']=='SYNTHETIC_DEMO' and result['reviewRequired'] is True,'RESULT_SCOPE')
    require(bool(result['limitations']),'RESULT_SCOPE')
    visits,latest,index,features,eligible,blocked=context(payload)
    missing=sorted(FEATURES-set(features));require(sorted(result['missingModalities'])==missing,'MISSING_MODALITIES')
    stages=result['stages'];expected=('DATA_FUSION',) if blocked else STAGES
    require(tuple(stage['stage'] for stage in stages)==expected and result['currentStage']==expected[-1],'STAGE_SEQUENCE')
    summary=stages[0]['summary']
    require(all(type(summary.get(key)) is int for key in ('visitCount','featureCount','excludedPostIndexFeatures'))
            and isinstance(summary.get('missingModalities'),list),'FUSION_EVIDENCE')
    require(summary.get('indexDate')==index and summary.get('visitCount')==len(visits)
            and summary.get('featureCount')==len(features) and summary.get('excludedPostIndexFeatures')==len(payload['features'])-len(eligible)
            and sorted(summary.get('missingModalities',[]))==missing and summary.get('qualityRuleVersion')=='synthetic-qa-v1','FUSION_EVIDENCE')
    require((result['status']=='BLOCKED')==blocked,'QUALITY_GATE')
    graph=result['graph']
    if blocked:
        require(stages[0]['status']=='BLOCKED' and graph['nodes']==graph['edges']==graph['paths']==[]
                and result['explanations']==[] and bool(result['warnings']),'BLOCKED_HAS_OUTPUT')
        return result
    require(all(stage['status']=='COMPLETED' for stage in stages),'STAGE_SEQUENCE')
    require((result['qualityStatus']=='WARN')==bool(result['warnings']),'QUALITY_WARNINGS')
    require(graph['graphVersion']=='synthetic-prior-v1','GRAPH_VERSION')
    nodes={node['id']:node for node in graph['nodes']}
    require(len(nodes)==len(graph['nodes'])==5 and set(nodes)==FEATURES|{'COGNITION','WARNING'},'GRAPH_NODES')
    for key,node in nodes.items():
        active=key in features or key in ('COGNITION','WARNING')
        require(node['status']==('ACTIVE' if active else 'MISSING'),'GRAPH_ACTIVATION')
        if key in FEATURES:require(node.get('observedAt')==(features.get(key) or {}).get('recordedAt'),'GRAPH_SOURCE_DATE')
    edge_map={(edge['from'],edge['to']):edge for edge in graph['edges']}
    expected_edges={(key,'COGNITION') for key in FEATURES}|{('COGNITION','WARNING')}
    require(len(edge_map)==len(graph['edges'])==4 and set(edge_map)==expected_edges,'GRAPH_EDGES')
    for (source,_),edge in edge_map.items():require(edge['status']==nodes[source]['status'],'GRAPH_ACTIVATION')
    paths=graph['paths'];require(len(paths)==4,'GRAPH_PATHS')
    require({tuple(path['nodes']) for path in paths}==expected_edges,'GRAPH_PATHS')
    for path in paths:require(path['status']==edge_map[tuple(path['nodes'])]['status'],'GRAPH_PATHS')
    explanations=result['explanations'];terms={item['feature'] for item in explanations}
    wanted={label for name,label in [('mmse','MMSE'),('moca','MoCA'),('cdrSb','CDR_SB')] if latest.get(name) is not None}
    if len(visits)>=2 and visits[0].get('mmse') is not None and latest.get('mmse') is not None:wanted.add('MMSE_DELTA')
    if 'APOE_E4_COUNT' in features:wanted.add('APOE_E4_COUNT')
    if {'MRI_HIPPOCAMPUS_L','MRI_HIPPOCAMPUS_R'}&set(features):wanted.add('MRI_HIPPOCAMPUS')
    require(len(terms)==len(explanations) and terms==wanted,'EXPLANATION_SOURCES')
    require(all(item['source']=='graph-masked-synthetic-rule-v1' for item in explanations),'EXPLANATION_SOURCES')
    score=result['riskScore'];require(.05<=score<=.95 and abs(score-round(score,4))<=1e-12,'SCORE_PRECISION')
    reconstructed=max(.05,min(.95,.18+sum(item['contribution'] for item in explanations)))
    # Each original contribution and the final score are rounded to four decimals.
    tolerance=(len(explanations)+1)*.00005+1e-12
    require(abs(reconstructed-score)<=tolerance,'EXPLANATION_RECONSTRUCTION')
    level=result['riskLevel'];rounding=.00005+1e-12
    require((level=='LOW' and score<=.34+rounding) or (level=='MEDIUM' and .34-rounding<=score<=.65+rounding)
            or (level=='HIGH' and score>=.65-rounding),'SCORE_LEVEL')
    return result
