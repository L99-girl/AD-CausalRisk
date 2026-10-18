"""Strict in-memory research record mapping for an authorized backend caller.

No HTTP route, disk export, patient summary, estimator or business API is added.
"""
from datetime import date
import hashlib
import json
import re
from .workbench_client import validate_result, alias_valid, number, ClientError, MODEL, FAMILIES

STAGES = ('SOURCE_INTEGRATION', 'PARTICIPANT_GRAPH', 'RISK_PREDICTION', 'PREDICTION_EXPLANATION')
UNITS = {'birth_year': 'year', 'age_years': 'years', 'education_years': 'years',
         'mmse': 'score', 'cdr_sb': 'score', 'cdr_global': 'score'}
RANGES = {'birth_year': (1800, 2100), 'age_years': (0, 120), 'education_years': (0, 40),
          'mmse': (0, 30), 'cdr_sb': (0, 18), 'cdr_global': (0, 3)}


class ResearchRecordError(ValueError):
    """Only safe codes; never interpolate clinical data or upstream exceptions."""


def require(condition, code):
    if not condition:raise ResearchRecordError(code)


def canonical_date(value):
    require(isinstance(value, str), 'SOURCE_DATE')
    try:parsed = date.fromisoformat(value)
    except ValueError:raise ResearchRecordError('SOURCE_DATE') from None
    require(parsed.isoformat() == value, 'SOURCE_DATE')
    return parsed


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def project_graph(graph, nodes, indexed):
    """Preserve dependency links; upstream retains its full derivation-value gate."""
    measured={node['id']:node for node in nodes};derived=[];all_ids=set(measured)
    raw=graph['derived_nodes']
    require(isinstance(raw,list) and len(raw)<=4,'DERIVED_NODES')
    for node in raw:
        identifier=node['id'];references=node['source_nodes']
        allowed={'age_years_at_landmark','mmse_slope','cdr_sb_slope','cdr_global_slope'}
        require(identifier in allowed and identifier not in all_ids and number(node['value']),'DERIVED_NODES')
        require(isinstance(references,list) and bool(references) and len(set(references))==len(references)
                and all(reference in measured for reference in references),'DERIVED_SOURCE_LINK')
        feature='birth_year' if identifier=='age_years_at_landmark' else identifier.removesuffix('_slope')
        require(all(measured[reference]['feature']==feature for reference in references),'DERIVED_SOURCE_LINK')
        if feature=='birth_year':
            require(len(references)==1 and abs(node['value']-(indexed.year-measured[references[0]]['value']))<=1e-12,'DERIVED_AGE')
        else:
            require(len(references)>=2 and measured[references[0]]['days_before_landmark']-measured[references[-1]]['days_before_landmark']>=30,'DERIVED_SOURCE_LINK')
        unit='years' if feature=='birth_year' else 'score/year'
        require(node.get('unit',unit)==unit,'DERIVED_UNIT')
        derived.append({'id':identifier,'value':node['value'],'unit':unit,'sourceNodeIds':list(references),
                        'derivation':'index_calendar_year_minus_birth_year' if feature=='birth_year' else 'OLS_slope_per_year',
                        'precision':'calendar_year_approximation' if feature=='birth_year' else None})
        all_ids.add(identifier)
    aliases=graph['current_feature_nodes']
    require(isinstance(aliases,dict) and set(aliases)<=FAMILIES
            and all(isinstance(reference,str) and reference in all_ids for reference in aliases.values()),'CURRENT_SOURCE_LINK')
    by_id={**measured,**{node['id']:node for node in raw}}
    for feature,reference in aliases.items():
        require(reference=='age_years_at_landmark' if feature=='age_years' else reference in measured and by_id[reference]['feature']==feature,'CURRENT_SOURCE_LINK')
    chronology=graph['chronological_edges'];require(isinstance(chronology,list),'SOURCE_CHRONOLOGY')
    expected=set()
    for feature in ('mmse','cdr_sb','cdr_global'):
        values=sorted((node for node in nodes if node['feature']==feature),key=lambda node:-node['days_before_landmark'])
        expected.update((a['id'],b['id']) for a,b in zip(values,values[1:]))
    links=[(edge['source'],edge['target']) for edge in chronology]
    require(len(set(links))==len(links) and set(links)==expected,'SOURCE_CHRONOLOGY')
    return derived,dict(aliases),[{'source':source,'target':target} for source,target in links],all_ids


def build_research_record(result, *, expected_alias, expected_model_sha256):
    """Validate a completed current result; return a fresh whitelisted record.

    expected_model_sha256 comes from the caller's independently bound model
    manifest, not from the untrusted response being checked. Keep return values
    in an authorized process: export_allowed=False remains effective.
    """
    require(alias_valid(expected_alias), 'EXPECTED_ALIAS')
    require(isinstance(expected_model_sha256, str) and re.fullmatch('[0-9a-f]{64}', expected_model_sha256) is not None, 'MODEL_PIN_REQUIRED')
    try:
        validate_result(result, expected_alias)
        core = result['core']; qualification = result['qualification']
        require(core['modelArtifactSha256'] == expected_model_sha256, 'MODEL_ARTIFACT_MISMATCH')
        require(core['qualityStatus'] in ('PASS', 'WARN'), 'RESULT_QUALITY')
        require(qualification['historical_availability_verified'] is False
                and qualification['future_outcomes_used_as_features'] is False, 'QUALIFICATION_BOUNDARY')
        indexed = canonical_date(qualification['index_date'])
        require(result['training_membership'] == 'NOT_REVERIFIED_POSSIBLE_DEVELOPMENT_RECORD', 'TRAINING_MEMBERSHIP')
        graph = core['graph']; nodes = graph['nodes']
        require(isinstance(nodes, list) and 0 < len(nodes) <= 1000, 'SOURCE_NODES')
        sources = []; identifiers = set()
        for node in nodes:
            identifier, feature, value = node['id'], node['feature'], node['value']
            require(isinstance(identifier, str) and 0 < len(identifier) <= 160 and identifier not in identifiers, 'SOURCE_ID')
            identifiers.add(identifier)
            require(feature in UNITS and node['unit'] == UNITS[feature], 'SOURCE_UNIT')
            require(number(value) and RANGES[feature][0] <= value <= RANGES[feature][1], 'SOURCE_VALUE')
            if feature == 'mmse':require(value == int(value), 'MMSE_TOTAL_NOT_INTEGER')
            if feature == 'cdr_global':require(value in (0, .5, 1, 2, 3), 'CDR_GLOBAL_NOT_ALLOWED')
            if feature == 'cdr_sb':require(value * 2 == int(value * 2) and value not in (16.5, 17.5), 'CDR_SB_TOTAL_NOT_ALLOWED')
            measured = canonical_date(node['measurement_date']); lag = (indexed-measured).days
            require(type(node['days_before_landmark']) is int and lag >= 0 and node['days_before_landmark'] == lag, 'SOURCE_CHRONOLOGY')
            for field in ('source_table', 'source_visit'):
                require(isinstance(node[field], str) and 0 < len(node[field]) <= 160 and node[field].strip() == node[field], 'SOURCE_PROVENANCE')
            require(not node['source_visit'].startswith(('DEMO-', 'SYNTH-')), 'SYNTHETIC_SOURCE_IN_REAL_RECORD')
            sources.append({'id': identifier, 'feature': feature, 'value': value, 'unit': node['unit'],
                            'measurementDate': measured.isoformat(), 'availableDate': None, 'daysBeforeIndex': lag,
                            'sourceTable': node['source_table'], 'sourceVisit': node['source_visit']})
        require(set(result['availability']) == identifiers, 'AVAILABILITY_NODE_LINK')
        derived,current,chronology,all_ids=project_graph(graph,nodes,indexed)
        bindings = result['source_bindings']
        require(isinstance(bindings, dict) and bool(bindings), 'SOURCE_BINDINGS')
        for key, item in bindings.items():
            require(isinstance(key, str) and 0 < len(key) <= 160 and isinstance(item, dict)
                    and isinstance(item.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', item['sha256']) is not None, 'SOURCE_BINDINGS')
        stages = core['stages']
        require(isinstance(stages, list) and tuple(stage['stage'] for stage in stages) == STAGES, 'STAGE_EVIDENCE')
        # These runtime stages do not record durations. Missing timing stays null.
        missing = core['missingInputs']
        require(isinstance(missing, list) and all(isinstance(value, str) and re.fullmatch('[a-z][a-z0-9_]{0,100}', value) for value in missing), 'MISSING_INPUTS')
        require(len(set(missing)) == len(missing), 'MISSING_INPUTS')
        require(core['qualityStatus'] == ('WARN' if missing else 'PASS'), 'RESULT_QUALITY')
        interactions = graph['interaction_edges']
        require(isinstance(interactions, list) and len(interactions) <= 100, 'INTERACTION_EVIDENCE')
        prior = []
        for edge in interactions:
            endpoints = edge['endpoints']
            require(isinstance(endpoints, list) and len(endpoints) == 2
                    and all(isinstance(value, str) and re.fullmatch('[a-z][a-z0-9_]{0,100}', value) for value in endpoints)
                    and type(edge['active']) is bool and edge['causal_effect_identified'] is False, 'INTERACTION_EVIDENCE')
            references=edge['node_endpoints']
            expected=[current.get(feature) if feature in FAMILIES else feature if feature in all_ids else None for feature in endpoints]
            require(references==expected and edge['active']==all(reference is not None for reference in expected),'INTERACTION_SOURCE_LINK')
            prior.append({'endpoints': list(endpoints), 'sourceNodeIds':list(references), 'active': edge['active']})
        ad = core['adCumulativeIncidence']; other = core['otherDementiaCumulativeIncidence']
        explanation = core['explanation']
        record = {'recordType': 'RETROSPECTIVE_RESEARCH', 'alias': expected_alias, 'indexDate': indexed.isoformat(),
                  'modelVersion': MODEL, 'modelArtifactSha256': expected_model_sha256,
                  'computationContract': result['computation_contract'], 'predictionWindowMonths': 24,
                  'endpoint': 'RECORDED_AD_DIAGNOSIS_WITH_COMPETING_DEMENTIA', 'qualityStatus': core['qualityStatus'],
                  'probabilities': {'adCif': ad, 'otherDementiaCif': other, 'unit': 'proportion'},
                  'sourceNodes': sources, 'sourceBindings': {key: {'sha256': item['sha256']} for key,item in bindings.items()},
                  'missingInputs': list(missing), 'priorInteractions': prior,'derivedNodes':derived,
                  'currentFeatureNodes':current,'chronologicalEdges':chronology,
                  'attribution': {'reference': explanation['reference'], 'baseline': explanation['baseline'],
                                  'contributions': [{'sourceFamily':item['sourceFamily'], 'contribution':item['contribution']}
                                                    for item in explanation['contributions']],
                                  'reconstructionResidual': explanation['reconstructionResidual'],
                                  'unit': 'probability_proportion', 'causalEffectIdentified': False},
                  'stages': [{'stage': stage, 'durationMs': None} for stage in STAGES],
                  'boundaries': {'clinicalUseEstablished': False, 'historicalAvailabilityVerified': False,
                                 'historicalRealtimePredictionAvailable': False, 'outOfSample': None,
                                 'trainingMembershipReverified': False, 'exportAllowed': False,
                                 'individualPredictionInterval': None, 'causalEffectIdentified': False}}
        record['recordSha256'] = digest(record)
        return record
    except ClientError:
        raise ResearchRecordError('RESULT_CONTRACT') from None
    except (KeyError, TypeError, AttributeError, OverflowError):
        raise ResearchRecordError('RECORD_SHAPE') from None
