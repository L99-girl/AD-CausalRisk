package com.adcausalrisk.backend.common;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.ResponseEntity;

/**
 * Unit tests for the handlers that only matter because they previously fell through to the
 * catch-all and produced a 500.
 */
class GlobalExceptionHandlerTest {

    /**
     * A constraint violation is now a validation failure. The import commit relies on this: the
     * data can move between preview and commit (a subject is deleted, a code is taken), and that
     * must not surface as a server error.
     */
    @Test
    void integrityViolationIsReportedAsValidationErrorNotServerError() {
        ResponseEntity<Envelope<Void>> response = new GlobalExceptionHandler()
                .handleIntegrityViolation(new DataIntegrityViolationException("uq_subject_code"));

        assertThat(response.getStatusCode().value()).isEqualTo(400);

        Envelope<Void> body = response.getBody();
        assertThat(body).isNotNull();
        assertThat(body.errorCode()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.message()).contains("重新预览");
    }
}
