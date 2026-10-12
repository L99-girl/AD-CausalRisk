package com.adcausalrisk.backend.common;

import java.time.Instant;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * The unified Java business response, frozen by
 * {@code contracts/java-business.target.openapi.json}.
 *
 * <p>Exactly six properties, all of them required, and {@code additionalProperties:
 * false} in the contract - so this record must not grow fields. Declaration order matches
 * the contract's property order.
 *
 * <p>Success is {@code code == 0} with {@code errorCode == null}; failure is a non-zero
 * {@code code} plus a stable {@link ErrorCode} name (SRS V3.2, "冻结的集成语义").
 *
 * <p>{@code data} is required and must be present as JSON {@code null} when there is no
 * payload. {@code @JsonInclude(ALWAYS)} is declared here as well as globally in
 * {@code JacksonConfig} on purpose: a later global Jackson change must not be able to
 * silently drop the key and break the contract.
 */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record Envelope<T>(
        int code,
        String message,
        T data,
        String errorCode,
        String traceId,
        Instant timestamp) {

    private static final int SUCCESS_CODE = 0;

    private static final String SUCCESS_MESSAGE = "成功";

    public static <T> Envelope<T> success(T data) {
        return new Envelope<>(SUCCESS_CODE, SUCCESS_MESSAGE, data, null, TraceId.current(), Instant.now());
    }

    public static <T> Envelope<T> failure(ErrorCode errorCode, String message) {
        return new Envelope<>(errorCode.code(), message, null, errorCode.name(), TraceId.current(), Instant.now());
    }
}
