package com.adcausalrisk.backend.security;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

import com.adcausalrisk.backend.common.Envelope;
import com.adcausalrisk.backend.common.ErrorCode;
import com.adcausalrisk.backend.common.TraceId;
import com.fasterxml.jackson.databind.ObjectMapper;

import jakarta.servlet.http.HttpServletResponse;

/**
 * Writes an {@link Envelope} from inside the Spring Security filter chain, where no
 * controller and no {@code @RestControllerAdvice} can run.
 *
 * <p>It exists so {@link RestAuthenticationEntryPoint} and {@link RestAccessDeniedHandler}
 * produce byte-identical error shapes to the rest of the API: a 401 or 403 from the security
 * chain must not look different from a 401 or 403 from a controller.
 */
final class SecurityEnvelopes {

    private SecurityEnvelopes() {
    }

    static void write(HttpServletResponse response, ObjectMapper objectMapper, ErrorCode errorCode)
            throws IOException {
        Envelope<Void> envelope = Envelope.failure(errorCode, errorCode.defaultMessage());

        response.setStatus(errorCode.status().value());
        response.setContentType("application/json");
        // Set the charset explicitly so the Chinese message is decoded correctly by clients
        // that follow the Content-Type header rather than guessing.
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        // TraceIdFilter already set this header before the security chain ran; repeating it
        // from the envelope keeps header and body consistent if the ordering ever changes.
        response.setHeader(TraceId.HEADER, envelope.traceId());

        objectMapper.writeValue(response.getOutputStream(), envelope);
    }
}
