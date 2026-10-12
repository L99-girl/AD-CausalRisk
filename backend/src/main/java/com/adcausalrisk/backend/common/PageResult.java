package com.adcausalrisk.backend.common;

import java.util.List;

/**
 * Shape of the contract's {@code PageSubject}: {@code items}, {@code page},
 * {@code pageSize}, {@code total} - and nothing else.
 *
 * <p>{@code page} is 1-based, and {@code pageSize} is limited to the contract maximum of
 * 100 by the calling service. Out-of-range values are rejected with a 400 rather than
 * silently clamped, so a broken caller cannot look successful.
 */
public record PageResult<T>(List<T> items, int page, int pageSize, long total) {
}
