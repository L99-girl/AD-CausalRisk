package com.adcausalrisk.backend.common;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.dao.CannotAcquireLockException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.PessimisticLockingFailureException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.MultipartException;

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

    /**
     * Waiting too long for the import row lock must not surface as a server error either: a second
     * commit that cannot take the lock within the database's limit is a "try again" condition.
     */
    @Test
    void lockWaitTimeoutIsReportedAsValidationErrorNotServerError() {
        ResponseEntity<Envelope<Void>> lockTimeout = new GlobalExceptionHandler()
                .handleLockConflict(new CannotAcquireLockException("lock wait timeout exceeded"));
        ResponseEntity<Envelope<Void>> pessimistic = new GlobalExceptionHandler()
                .handleLockConflict(new PessimisticLockingFailureException("could not lock row"));

        for (ResponseEntity<Envelope<Void>> response : List.of(lockTimeout, pessimistic)) {
            assertThat(response.getStatusCode().value()).isEqualTo(400);
            Envelope<Void> body = response.getBody();
            assertThat(body).isNotNull();
            assertThat(body.errorCode()).isEqualTo("VALIDATION_ERROR");
            assertThat(body.message()).contains("稍后重试");
        }
    }

    /**
     * A multipart request Spring cannot parse at all (missing boundary, truncated body) is raised
     * before the controller, so it needs its own handler or it becomes a 500 for a client error.
     * The oversized-upload handler must keep its more specific message, because
     * {@code MaxUploadSizeExceededException} is a subclass of this type.
     */
    @Test
    void malformedMultipartIsReportedAsValidationErrorNotServerError() {
        GlobalExceptionHandler handler = new GlobalExceptionHandler();

        ResponseEntity<Envelope<Void>> malformed =
                handler.handleMalformedMultipart(new MultipartException("no multipart boundary"));
        ResponseEntity<Envelope<Void>> oversized =
                handler.handleOversizedUpload(new MaxUploadSizeExceededException(1024L));

        assertThat(malformed.getStatusCode().value()).isEqualTo(400);
        assertThat(malformed.getBody()).isNotNull();
        assertThat(malformed.getBody().errorCode()).isEqualTo("VALIDATION_ERROR");
        assertThat(malformed.getBody().message()).contains("multipart");

        assertThat(oversized.getStatusCode().value()).isEqualTo(400);
        assertThat(oversized.getBody()).isNotNull();
        assertThat(oversized.getBody().message()).contains("大小限制");
    }
}
