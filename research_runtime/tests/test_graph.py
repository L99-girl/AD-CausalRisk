"""Unfitted numerical calculations only; no clinical files or model loading."""
from copy import deepcopy
import math
import unittest
import numpy as np
from research_runtime import graph as g


def parameters():
    projection=np.zeros((2,8));projection[0,0]=1;projection[1,1]=.2
    head=np.zeros((104,3));head[8*8,1]=.8
    return {'input_projection':projection,'node_embeddings':np.full((10,8),.1),
            'layers':[{'weight':np.eye(8),'attention':np.zeros(16)} for _ in range(2)],'head':head}


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.values=np.tile(np.linspace(.1,1,10),(2,1));self.observed=np.ones((2,10),dtype=bool)
        self.parameters=parameters()

    def test_three_arms_preserve_nodes_and_semantic_control_topology(self):
        spec,_=g.protocol();a=g.arm_edges('prior');b=g.arm_edges('semantic_permutation')
        self.assertEqual(g.arm_edges('self_only'),())
        self.assertEqual((len(a),len(b)),(11,11));self.assertNotEqual(set(a),set(b))
        self.assertEqual(sorted(sum(x==i for x,_ in a) for i in range(10)),
                         sorted(sum(x==i for x,_ in b) for i in range(10)))
        self.assertEqual(sorted(sum(y==i for _,y in a) for i in range(10)),
                         sorted(sum(y==i for _,y in b) for i in range(10)))
        touched={spec['features'][i] for edge in a for i in edge}
        self.assertEqual(set(spec['unsupported_cross_route_features']),set(spec['features'])-touched)

    def test_observed_endpoint_gates_and_self_loops_for_missing_nodes(self):
        self.observed[0,7]=False;self.observed[1,8]=False
        allowed=g.allowed_routes(self.observed,g.arm_edges('prior'))
        self.assertFalse(allowed[0,7,8]);self.assertFalse(allowed[1,0,8]);self.assertFalse(allowed[1,8,2])
        self.assertTrue(np.diagonal(allowed,axis1=1,axis2=2).all())

    def test_attention_normalizes_over_sources_and_never_uses_forbidden_routes(self):
        self.observed[0,8]=False
        result=g.reference_forward(self.values,self.observed,'prior',self.parameters)
        for alpha in result['attention']:
            np.testing.assert_allclose(alpha.sum(axis=1),1,atol=1e-15)
            self.assertTrue((alpha[~result['allowed_routes']]==0).all())
        self.assertEqual(result['attention'][0][0,8,8],1)

    def test_explicit_graph_change_reaches_states_and_cif_with_same_inputs_and_parameters(self):
        results={arm:g.reference_forward(self.values,self.observed,arm,self.parameters) for arm in ('self_only','prior','semantic_permutation')}
        for arm in ('self_only','semantic_permutation'):
            np.testing.assert_array_equal(results['prior']['encoded'],results[arm]['encoded'])
            self.assertGreater(np.max(abs(results['prior']['states']-results[arm]['states'])),1e-8)
            self.assertGreater(np.max(abs(results['prior']['cif']-results[arm]['cif'])),1e-8)

    def test_missing_values_do_not_become_messages_or_fabricated_observations(self):
        self.observed[:,7]=False;values=self.values.copy();values[:,7]=np.nan
        a=g.reference_forward(values,self.observed,'prior',self.parameters)
        values[:,7]=100000
        b=g.reference_forward(values,self.observed,'prior',self.parameters)
        np.testing.assert_array_equal(a['cif'],b['cif'])
        self.assertTrue(np.isfinite(a['states']).all())

    def test_attention_weights_can_vary_by_personal_observations(self):
        self.values[1,7]+=2
        for layer in self.parameters['layers']:layer['attention'][0]=1
        result=g.reference_forward(self.values,self.observed,'prior',self.parameters)
        self.assertGreater(abs(result['attention'][0][0,7,8]-result['attention'][0][1,7,8]),1e-8)
        self.assertGreater(np.max(abs(result['states'][0]-result['states'][1])),1e-8)

    def test_vectorized_messages_match_independent_scalar_sum(self):
        rng=np.random.default_rng(30)
        params=deepcopy(self.parameters)
        for layer in params['layers']:
            layer['attention']=rng.normal(size=16)*.1
        result=g.reference_forward(self.values,self.observed,'prior',params)
        states=result['encoded'].copy();allowed=result['allowed_routes']
        for layer in params['layers']:
            q=states@layer['weight'];expected=np.zeros_like(states)
            for person in range(2):
                for target in range(10):
                    sources=[source for source in range(10) if allowed[person,source,target]]
                    scores=[float(np.r_[q[person,source],q[person,target]]@layer['attention']) for source in sources]
                    scores=[score if score>=0 else .2*score for score in scores]
                    weights=[math.exp(score-max(scores)) for score in scores]
                    for source,weight in zip(sources,weights):
                        expected[person,target]+=weight/sum(weights)*q[person,source]
            states=np.maximum(expected,0)
        np.testing.assert_allclose(result['states'],states,rtol=1e-14,atol=1e-14)

    def test_constant_hazard_has_analytic_two_cause_cif_and_no_false_graph_effect(self):
        self.parameters['head'][:]=0
        a=g.reference_forward(self.values,self.observed,'prior',self.parameters)
        b=g.reference_forward(self.values,self.observed,'self_only',self.parameters)
        np.testing.assert_array_equal(a['cif'],b['cif'])
        expected=.5*(1-(1/3)**24)
        np.testing.assert_allclose(a['cif'][:,:2],expected,atol=1e-14)
        np.testing.assert_allclose(a['cif'].sum(axis=1),1,atol=1e-14)
        self.assertFalse(a['individual_causal_effect_identified']);self.assertFalse(a['clinical_use'])

    def test_bad_edges_masks_parameters_and_nonfinite_observations_rejected(self):
        for edges in [[(0,0)],[(0,8),(0,8)],[(True,8)],[(0,10)]]:
            with self.assertRaises(ValueError):g.allowed_routes(self.observed,edges)
        bad=self.observed.astype(int);bad[0,0]=2
        with self.assertRaises(ValueError):g.allowed_routes(bad,())
        values=self.values.copy();values[0,0]=np.inf
        with self.assertRaises(ValueError):g.reference_forward(values,self.observed,'prior',self.parameters)
        badparams=deepcopy(self.parameters);badparams['head']=np.zeros((103,3))
        with self.assertRaises(ValueError):g.reference_forward(self.values,self.observed,'prior',badparams)

    def test_reference_does_not_mutate_inputs_or_parameters(self):
        values=self.values.copy();observed=self.observed.copy();before=deepcopy(self.parameters)
        g.reference_forward(self.values,self.observed,'prior',self.parameters)
        np.testing.assert_array_equal(values,self.values);np.testing.assert_array_equal(observed,self.observed)
        for key in ('input_projection','node_embeddings','head'):
            np.testing.assert_array_equal(self.parameters[key],before[key])
        for a,b in zip(self.parameters['layers'],before['layers']):
            for key in a:np.testing.assert_array_equal(a[key],b[key])


if __name__=='__main__':unittest.main()
