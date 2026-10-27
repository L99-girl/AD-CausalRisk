"""Run original CIF arithmetic with constructed metadata and constant hazards.

No clinical reader, parameter artifact, optimizer or fitted model is involved.
Only aggregate operation status is printed; individual results stay in memory.
"""
import hashlib
import json
from types import SimpleNamespace

import numpy as np

from research_runtime.examples.input_admission_constructed import constructed_pair
from research_runtime.inmemory_inference import (
    authorize_once, bind_existing_model, run_in_memory,
)


def main():
    request, context = constructed_pair()
    hazards = np.array([.94, .04, .02])
    classes = np.array([0, 1, 2])
    model = SimpleNamespace(named_steps={'hazards': SimpleNamespace(classes_=classes)},
                            predict_proba=lambda frame: np.tile(hazards, (len(frame), 1)))
    predictor = bind_existing_model(model, verified_identity=context['model'],
        state_token=lambda: hashlib.sha256(hazards.tobytes()+classes.tobytes()).hexdigest())
    waiting = run_in_memory(request, trusted_context=context, predictor=predictor)
    assert waiting['status'] == 'PERMISSION_REQUIRED' and waiting['predictionCalls'] == 0
    permit = authorize_once(request, trusted_context=context,
                            authorization_ref='CONSTRUCTED-EXAMPLE', authorization_granted=True)
    completed = run_in_memory(request, trusted_context=context, predictor=predictor, permit=permit)
    assert completed['status'] == 'COMPLETED' and completed['predictionCalls'] == 1
    print(json.dumps(dict(status=completed['status'], purpose='CONSTRUCTED_ACCEPTANCE',
        constructedRecords=completed['admission']['recordCount'],
        callsWithoutPermit=waiting['predictionCalls'], callsWithPermit=completed['predictionCalls'],
        permitState=permit.state, clinicalUse=completed['clinicalUse'],
        metadataPredictionAllowed=completed['admission']['predictionAllowed']), allow_nan=False))


if __name__ == '__main__':
    main()
