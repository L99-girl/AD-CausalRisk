"""Validate old request boundary without model loading, fitting or prediction."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from research_runtime.input_admission import FEATURES, UNITS, validate_snapshot, AdmissionError
from research_runtime.examples.input_admission_constructed import constructed_pair
from research_runtime import inference
from research_runtime.estimators import SPECS, FAMILIES


def synthetic_request(spec='multimodal_values', family='logistic'):
    request,_=constructed_pair('seven' if spec=='seven' else 'multimodal_values',family)
    features={name:{k:item[k] for k in ('value','unit','measuredDate','availableDate')}
              for name,item in request['records'][0]['features'].items()}
    for item in features.values():item.update(source='SYNTHETIC',qc='SYNTHETIC')
    return dict(schemaVersion=inference.SCHEMA,purpose='SYNTHETIC_ACCEPTANCE',specification=spec,
                family=family,dataVersion='synthetic-constructed-v1',indexDate=request['indexDate'],
                predictionWindowMonths=24,records=[dict(subjectCode='SYNTHETIC-001',features=features)])


class AdmissionCompatibilityTests(unittest.TestCase):
    def test_feature_order_units_and_existing_final_roles_still_match(self):
        self.assertEqual(FEATURES,SPECS['multimodal_values']);self.assertEqual(UNITS,inference.UNITS)
        for spec in ('seven','multimodal_values'):
            request,_=constructed_pair(spec,'logistic')
            self.assertEqual(request['model']['role'],inference.ROLES[spec])

    def test_existing_synthetic_validation_all_nine_models_without_loading(self):
        for spec in SPECS:
            for family in FAMILIES:
                request=synthetic_request(spec,family);before=deepcopy(request)
                frame,sources=inference.validate_request(request)
                self.assertEqual(len(frame),1);self.assertEqual(len(sources),1);self.assertEqual(request,before)
                self.assertEqual(frame['apoe4_count'].iloc[0],0 if spec=='modality_availability' else 1) if spec!='seven' else None

    def test_real_format_rejected_by_existing_cli_before_any_model_call(self):
        request,_=constructed_pair()
        with patch.object(inference,'load_final_model') as loader,patch.object(inference,'predict_cif') as predictor:
            with self.assertRaises(ValueError):inference.run_acceptance(request,'UNUSED','0'*64)
            loader.assert_not_called();predictor.assert_not_called()

    def test_old_synthetic_format_does_not_satisfy_new_evidence_contract(self):
        _,context=constructed_pair()
        with self.assertRaises(AdmissionError):validate_snapshot(synthetic_request(),trusted_context=context)

    def test_mutating_synthetic_purpose_cannot_enable_real_inference(self):
        request=synthetic_request();request['purpose']='OFFLINE_RESEARCH_ADMISSION'
        with patch.object(inference,'load_final_model') as loader:
            with self.assertRaisesRegex(ValueError,'SYNTHETIC_ACCEPTANCE_ONLY'):
                inference.run_acceptance(request,'UNUSED','0'*64)
            loader.assert_not_called()


if __name__=='__main__':unittest.main()
