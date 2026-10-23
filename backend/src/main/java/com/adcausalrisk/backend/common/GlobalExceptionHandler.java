package com.adcausalrisk.backend.common;

import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.CannotAcquireLockException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.PessimisticLockingFailureException;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.support.MissingServletRequestPartException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import jakarta.validation.ConstraintViolationException;

/**
 * Turns every failure into the unified {@link Envelope} with a correct HTTP status.
 *
 * <p>Two rules matter here:
 *
 * <ul>
 *   <li>A refusal is never disguised as HTTP 200. The status comes from the
 *       {@link ErrorCode}, not from the handler.
 *   <li>An unexpected failure never leaks internals. The stack trace is logged and the
 *       caller receives the stable {@link ErrorCode#INTERNAL_ERROR} message only.
 * </ul>
 *
 * <p>Authentication and authorisation failures raised by the Spring Security filter chain
 * are handled there, not here, because they never reach a controller.
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(BusinessException.class)
    ResponseEntity<Envelope<Void>> handleBusinessFailure(BusinessException exception) {
        log.debug("business failure {}", exception.errorCode(), exception);
        return respond(exception.errorCode(), exception.getMessage());
    }

    /** {@code @Valid} on a request body. Reports the offending fields. */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<Envelope<Void>> handleInvalidBody(MethodArgumentNotValidException exception) {
        String detail = exception.getBindingResult().getFieldErrors().stream()
                .map(fieldError -> fieldError.getField() + " " + fieldError.getDefaultMessage())
                .sorted()
                .collect(Collectors.joining("; "));
        return respond(ErrorCode.VALIDATION_ERROR, detail.isEmpty() ? null : detail);
    }

    @ExceptionHandler(ConstraintViolationException.class)
    ResponseEntity<Envelope<Void>> handleConstraintViolation(ConstraintViolationException exception) {
        String detail = exception.getConstraintViolations().stream()
                .map(violation -> violation.getPropertyPath() + " " + violation.getMessage())
                .sorted()
                .collect(Collectors.joining("; "));
        return respond(ErrorCode.VALIDATION_ERROR, detail.isEmpty() ? null : detail);
    }

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    ResponseEntity<Envelope<Void>> handleTypeMismatch(MethodArgumentTypeMismatchException exception) {
        return respond(ErrorCode.VALIDATION_ERROR, exception.getName() + " 取值无效");
    }

    @ExceptionHandler(MissingServletRequestParameterException.class)
    ResponseEntity<Envelope<Void>> handleMissingParameter(MissingServletRequestParameterException exception) {
        return respond(ErrorCode.VALIDATION_ERROR, exception.getParameterName() + " 不能为空");
    }

    /**
     * Unreadable body: malformed JSON, or properties the contract does not define
     * ({@code JacksonConfig} enables FAIL_ON_UNKNOWN_PROPERTIES because every request
     * schema in the target contract sets {@code additionalProperties: false}).
     */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    ResponseEntity<Envelope<Void>> handleUnreadableBody(HttpMessageNotReadableException exception) {
        log.debug("unreadable request body", exception);
        return respond(ErrorCode.MALFORMED_JSON, null);
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    ResponseEntity<Envelope<Void>> handleUnsupportedMethod(HttpRequestMethodNotSupportedException exception) {
        return respond(ErrorCode.METHOD_NOT_ALLOWED, null);
    }

    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    ResponseEntity<Envelope<Void>> handleUnsupportedMediaType(HttpMediaTypeNotSupportedException exception) {
        return respond(ErrorCode.UNSUPPORTED_MEDIA_TYPE, null);
    }

    /** No route matched. Without this the catch-all below would report a 500. */
    @ExceptionHandler(NoResourceFoundException.class)
    ResponseEntity<Envelope<Void>> handleNoRoute(NoResourceFoundException exception) {
        return respond(ErrorCode.NOT_FOUND, null);
    }

    /**
     * A required header is missing - for an import preview that is {@code Idempotency-Key}.
     * Without this handler the catch-all would disguise the refusal as a 500.
     */
    @ExceptionHandler(MissingRequestHeaderException.class)
    ResponseEntity<Envelope<Void>> handleMissingHeader(MissingRequestHeaderException exception) {
        return respond(ErrorCode.VALIDATION_ERROR, exception.getHeaderName() + " 不能为空");
    }

    /** A required multipart part is missing - for an import preview that is {@code file}. */
    @ExceptionHandler(MissingServletRequestPartException.class)
    ResponseEntity<Envelope<Void>> handleMissingPart(MissingServletRequestPartException exception) {
        return respond(ErrorCode.VALIDATION_ERROR, exception.getRequestPartName() + " 不能为空");
    }

    /**
     * The upload exceeded {@code spring.servlet.multipart.max-file-size}. The target contract
     * declares no 413 for any operation, so an oversized upload is reported as a validation
     * failure like every other refused request - never as a 500.
     */
    @ExceptionHandler(MaxUploadSizeExceededException.class)
    ResponseEntity<Envelope<Void>> handleOversizedUpload(MaxUploadSizeExceededException exception) {
        log.debug("upload rejected because it exceeded the configured limit", exception);
        return respond(ErrorCode.VALIDATION_ERROR, "上传文件超过大小限制");
    }

    /**
     * A database constraint rejected the write. For the import commit this means the data moved
     * between preview and commit (a subject was deleted, a code was taken) or otherwise conflicts
     * with what is already stored. The contract declares no 409, so it is reported as a
     * validation failure - and never as a 500.
     */
    @ExceptionHandler(DataIntegrityViolationException.class)
    ResponseEntity<Envelope<Void>> handleIntegrityViolation(
            DataIntegrityViolationException exception) {
        log.debug("database constraint rejected the write", exception);
        return respond(ErrorCode.VALIDATION_ERROR,
                "数据在预览后发生变化或与现有数据冲突，请重新预览");
    }

    /**
     * A write could not take the row lock within the database's wait limit. For the import commit
     * this means another request is already committing the same job, so the caller should retry
     * instead of receiving a server error. {@link CannotAcquireLockException} is a subclass of
     * {@link PessimisticLockingFailureException}; both are listed to make the intent explicit.
     */
    @ExceptionHandler({CannotAcquireLockException.class, PessimisticLockingFailureException.class})
    ResponseEntity<Envelope<Void>> handleLockConflict(PessimisticLockingFailureException exception) {
        log.debug("row lock could not be acquired in time", exception);
        return respond(ErrorCode.VALIDATION_ERROR, "该任务正在处理中，请稍后重试");
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<Envelope<Void>> handleUnexpectedFailure(Exception exception) {
        log.error("unexpected failure", exception);
        return respond(ErrorCode.INTERNAL_ERROR, null);
    }

    private static ResponseEntity<Envelope<Void>> respond(ErrorCode errorCode, String message) {
        String bodyMessage = (message == null || message.isBlank()) ? errorCode.defaultMessage() : message;
        return ResponseEntity.status(errorCode.status()).body(Envelope.failure(errorCode, bodyMessage));
    }
}
