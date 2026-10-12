package com.adcausalrisk.backend.common;

/**
 * A business rule was violated. Carries the stable {@link ErrorCode} that
 * {@link GlobalExceptionHandler} turns into the HTTP status and the response Envelope.
 *
 * <p>The message is shown to the caller, so it must be readable and must not contain
 * internal detail. Use the {@link ErrorCode#defaultMessage()} form when there is nothing
 * operation-specific to add.
 */
public class BusinessException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    private final ErrorCode errorCode;

    public BusinessException(ErrorCode errorCode) {
        super(errorCode.defaultMessage());
        this.errorCode = errorCode;
    }

    public BusinessException(ErrorCode errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }

    public ErrorCode errorCode() {
        return errorCode;
    }
}
