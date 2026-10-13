package com.adcausalrisk.backend.common;

import java.util.UUID;
import java.util.regex.Pattern;

import org.slf4j.MDC;

/**
 * The single source of the request trace identifier.
 *
 * <p>{@link Envelope} reads it and {@link TraceIdFilter} writes it, so the trace id in
 * the response body, in the {@code X-Trace-Id} response header and in the server log is
 * always the same value.
 *
 * <p>The accepted shape is deliberately identical to the Python service
 * (python_service/server.py), so one identifier can span the browser &rarr; Java &rarr;
 * Python hops.
 */
public final class TraceId {

    /** MDC key; the logging pattern can reference it as {@code %X{traceId}}. */
    public static final String MDC_KEY = "traceId";

    /** Request and response header carrying the trace id. */
    public static final String HEADER = "X-Trace-Id";

    private static final Pattern VALID = Pattern.compile("[A-Za-z0-9._-]{1,64}");

    private TraceId() {
    }

    /** True when {@code candidate} may be accepted verbatim from a caller. */
    public static boolean isValid(String candidate) {
        return candidate != null && VALID.matcher(candidate).matches();
    }

    /** Generates a 32-character hex identifier. */
    public static String generate() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    /**
     * The current request's trace id, or a freshly generated one when no filter ran
     * (for example when an Envelope is built directly in a test).
     */
    public static String current() {
        String bound = MDC.get(MDC_KEY);
        return isValid(bound) ? bound : generate();
    }

    static void bind(String traceId) {
        MDC.put(MDC_KEY, traceId);
    }

    static void clear() {
        MDC.remove(MDC_KEY);
    }
}
