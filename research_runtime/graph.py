"""Numerical reference for an explicit graph-to-CIF computational route.

No training, model/data reader, HTTP or clinical use. Parameters are supplied by
the caller; tests use manually constructed constants. A differentiable training
implementation remains a separate, bounded task.
"""
import hashlib
import json
from pathlib import Path
import numpy as np


def protocol():
    path=Path(__file__).with_name('graph_protocol.json')
    raw=path.read_bytes();spec=json.loads(raw)
    if (spec['schemaVersion']!='graph-prediction-mechanism-v1'
            or len(spec['features'])!=10 or len(set(spec['features']))!=10
            or spec['architecture']['width']!=8 or spec['architecture']['layers']!=2
            or spec['architecture']['hazard_classes']!=[0,1,2]
            or spec['individual_causal_effect_identified'] or spec['clinical_use']):
        raise ValueError('INVALID_GRAPH_REFERENCE_SPECIFICATION')
    return spec,hashlib.sha256(raw).hexdigest()


def arm_edges(arm):
    spec,_=protocol();features=spec['features']
    if arm not in spec['arms']:raise ValueError('UNKNOWN_GRAPH_ARM')
    edges=[(features.index(a),features.index(b)) for a,b in spec['prior_edges']]
    if len(edges)!=11 or len(set(edges))!=11 or any(a==b for a,b in edges):
        raise ValueError('INVALID_PRIOR_ROUTES')
    if arm=='self_only':return ()
    if arm=='semantic_permutation':
        permutation=spec['semantic_permutation']
        if sorted(permutation)!=list(range(10)):raise ValueError('INVALID_SEMANTIC_PERMUTATION')
        edges=[(permutation[a],permutation[b]) for a,b in edges]
    return tuple(edges)


def _observed(mask):
    value=np.asarray(mask)
    if value.ndim!=2 or value.shape[1]!=10 or value.shape[0]==0 or not np.isin(value,[0,1]).all():
        raise ValueError('INVALID_OBSERVED_MASK')
    return value.astype(bool)


def _finite(value, shape):
    array=np.asarray(value,dtype=float)
    if array.shape!=shape or not np.isfinite(array).all():raise ValueError('INVALID_PARAMETER_OR_STATE')
    return array


def allowed_routes(observed, edges):
    observed=_observed(observed)
    allowed=np.broadcast_to(np.eye(10,dtype=bool),(len(observed),10,10)).copy()
    seen=set()
    for source,target in edges:
        if (type(source) not in (int,np.int64,np.int32) or type(target) not in (int,np.int64,np.int32)
                or source not in range(10) or target not in range(10) or source==target
                or (source,target) in seen):raise ValueError('INVALID_GRAPH_EDGE')
        seen.add((source,target))
        allowed[:,source,target]=observed[:,source]&observed[:,target]
    return allowed


def encode(values, observed, projection, embeddings):
    """Inputs are training-fold standardized; missing value channels are zero."""
    observed=_observed(observed);values=np.asarray(values,dtype=float)
    if values.shape!=observed.shape or not np.isfinite(values[observed]).all():
        raise ValueError('NONFINITE_OBSERVED_VALUE')
    channels=np.stack((np.where(observed,values,0),observed.astype(float)),axis=-1)
    projection=_finite(projection,(2,8));embeddings=_finite(embeddings,(10,8))
    states=np.maximum(0,channels@projection+embeddings)
    if not np.isfinite(states).all():raise ValueError('NONFINITE_ENCODING')
    return states


def message_pass(states, observed, edges, layers):
    observed=_observed(observed);states=_finite(states,(len(observed),10,8))
    if len(layers)!=2:raise ValueError('EXACTLY_TWO_MESSAGE_LAYERS_REQUIRED')
    allowed=allowed_routes(observed,edges);attention=[]
    for layer in layers:
        weight=_finite(layer['weight'],(8,8));a=_finite(layer['attention'],(16,))
        q=states@weight
        score=(q@a[:8])[:,:,None]+(q@a[8:])[:,None,:]
        score=np.where(score>=0,score,.2*score)
        if not np.isfinite(score).all():raise ValueError('NONFINITE_ATTENTION_LOGITS')
        score=np.where(allowed,score,-np.inf)
        maximum=score.max(axis=1,keepdims=True)
        exponent=np.exp(score-maximum)
        alpha=exponent/exponent.sum(axis=1,keepdims=True)
        states=np.maximum(0,np.einsum('nij,nid->njd',alpha,q))
        if not np.isfinite(states).all():raise ValueError('NONFINITE_MESSAGE_STATE')
        attention.append(alpha)
    return states,attention,allowed


def hazard_cif(states, head):
    states=np.asarray(states,dtype=float)
    if states.ndim!=3 or states.shape[1:]!=(10,8) or len(states)==0 or not np.isfinite(states).all():
        raise ValueError('INVALID_READOUT_STATES')
    head=_finite(head,(104,3))
    logits=(states.reshape(len(states),80)@head[:80])[:,None,:]+head[80:][None,:,:]
    probabilities=np.exp(logits-logits.max(axis=2,keepdims=True))
    probabilities/=probabilities.sum(axis=2,keepdims=True)
    survival=np.ones(len(states));ad=np.zeros(len(states));other=ad.copy()
    for month in range(24):
        ad+=survival*probabilities[:,month,1]
        other+=survival*probabilities[:,month,2]
        survival*=probabilities[:,month,0]
    if not np.isfinite(np.c_[ad,other,survival]).all() or not np.allclose(ad+other+survival,1,rtol=0,atol=1e-12):
        raise ValueError('INVALID_COMPETING_CIF')
    return probabilities,np.c_[ad,other,survival]


def reference_forward(values, observed, arm, parameters):
    """Expose the actual graph/mask/weights used by this unfitted calculation."""
    spec,digest=protocol()
    encoded=encode(values,observed,parameters['input_projection'],parameters['node_embeddings'])
    states,attention,allowed=message_pass(encoded,observed,arm_edges(arm),parameters['layers'])
    hazards,cif=hazard_cif(states,parameters['head'])
    return {'arm':arm,'protocol_sha256':digest,'encoded':encoded,'states':states,
            'allowed_routes':allowed,'attention':attention,'hazards':hazards,'cif':cif,
            'edge_semantics':spec['edge_semantics'],'calculation_only':True,
            'clinical_use':False,'individual_causal_effect_identified':False}
