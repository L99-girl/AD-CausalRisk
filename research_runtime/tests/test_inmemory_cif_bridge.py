"""Original CIF path with constructed fixed hazards, no fitted/loaded models."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from research_runtime.examples.input_admission_constructed import constructed_pair
from research_runtime.inmemory_inference import bind_existing_model, run_in_memory, InferenceError
from research_runtime.tests.test_inmemory_inference import permit_for, add_second
from research_runtime.tests.test_input_admission import missing
from research_runtime import discrete


class FixedHazards:
    def __init__(self,values=(.94,.04,.02),labels=(0,1,2)):
        self.values=np.asarray(values);self.named_steps={'hazards':SimpleNamespace(classes_=np.asarray(labels))}
        self.calls=0;self.grids=[];self.mutate=False
    def predict_proba(self,grid):
        self.calls+=1;self.grids.append(grid.copy(deep=True))
        if self.mutate:grid.iloc[0,0]=0
        return np.tile(self.values,(len(grid),1))
    def state(self):
        return hashlib.sha256(self.values.tobytes()+self.named_steps['hazards'].classes_.tobytes()).hexdigest()


class CIFBridgeTests(unittest.TestCase):
    def test_original_cif_called_once_and_matches_analytic_two_cause_solution(self):
        for spec,family in [('seven','logistic'),('multimodal_values','random_forest'),
                            ('multimodal_values','xgboost'),('multimodal_values','prior_graph')]:
            request,context=constructed_pair(spec,family);add_second(request,context);model=FixedHazards()
            predictor=bind_existing_model(model,verified_identity=context['model'],state_token=model.state)
            original=deepcopy(request)
            with patch.object(discrete,'predict_cif',wraps=discrete.predict_cif) as cif:
                result=run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit_for(request,context))
                self.assertEqual(cif.call_count,1)
            self.assertEqual(model.calls,1);self.assertEqual(len(model.grids[0]),48)
            expected=np.array([.04,.02])*(1-.94**24)/(1-.94)
            for row in result['predictions']:
                np.testing.assert_allclose([row['ad_cif_24m'],row['other_dementia_cif_24m']],expected,atol=1e-14,rtol=0)
            self.assertEqual(request,original)
            self.assertEqual(list(model.grids[0]),[*context['model']['features'],'month'])

    def test_missingness_reaches_original_predictor_without_zero_imputation(self):
        request,context=constructed_pair()
        for name in ('mmse','mri_left_hippocampus_volume','mri_right_hippocampus_volume'):
            missing(request,name,context=context)
        model=FixedHazards();predictor=bind_existing_model(model,verified_identity=context['model'],state_token=model.state)
        run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit_for(request,context))
        self.assertTrue(model.grids[0][['mmse','mri_left_hippocampus_volume','mri_right_hippocampus_volume']].isna().all().all())

    def test_permuted_class_order_is_mapped_by_original_cif(self):
        request,context=constructed_pair();model=FixedHazards((.02,.94,.04),(2,0,1))
        predictor=bind_existing_model(model,verified_identity=context['model'],state_token=model.state)
        result=run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit_for(request,context))
        expected=np.array([.04,.02])*(1-.94**24)/(1-.94)
        row=result['predictions'][0];np.testing.assert_allclose([row['ad_cif_24m'],row['other_dementia_cif_24m']],expected,atol=1e-14,rtol=0)

    def test_event_free_and_immediate_event_boundary_hazards(self):
        for hazards,expected in [((1.,0.,0.),(0.,0.)),((0.,1.,0.),(1.,0.)),((0.,0.,1.),(0.,1.))]:
            request,context=constructed_pair();model=FixedHazards(hazards)
            predictor=bind_existing_model(model,verified_identity=context['model'],state_token=model.state)
            row=run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit_for(request,context))['predictions'][0]
            self.assertEqual((row['ad_cif_24m'],row['other_dementia_cif_24m']),expected)

    def test_invalid_hazards_classes_and_grid_mutation_are_discarded(self):
        cases=[FixedHazards((.8,.4,.1)),FixedHazards((-.1,.9,.2)),FixedHazards((float('nan'),.5,.5)),
               FixedHazards((True,False,False)),FixedHazards((.94,.04,.02),(0,1,1)),FixedHazards((.94,.04),(0,1))]
        mutated=FixedHazards();mutated.mutate=True;cases.append(mutated)
        for model in cases:
            request,context=constructed_pair();predictor=bind_existing_model(model,verified_identity=context['model'],state_token=model.state)
            permit=permit_for(request,context)
            with self.assertRaisesRegex(InferenceError,'PREDICTOR_CALL_FAILED'):
                run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
            self.assertEqual(permit.state,'FAILED');self.assertLessEqual(model.calls,1)

    def test_lossy_integer_conversion_is_not_silently_accepted(self):
        request,context=constructed_pair();obs=request['records'][0]['features']['education_years'];obs['value']=2**53+1
        context['evidence'][obs['evidenceRef']]['observation']['value']=obs['value']
        model=FixedHazards();predictor=bind_existing_model(model,verified_identity=context['model'],state_token=model.state)
        with self.assertRaisesRegex(InferenceError,'PREDICTOR_CALL_FAILED'):
            run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit_for(request,context))
        self.assertEqual(model.calls,0)


if __name__=='__main__':unittest.main()
