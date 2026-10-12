package com.adcausalrisk.backend.common;

import java.io.IOException;

import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/**
 * Binds one trace id for the whole request so that {@link Envelope#traceId()}, the
 * {@code X-Trace-Id} response header and the server log agree.
 *
 * <p>Ordered at {@link Ordered#HIGHEST_PRECEDENCE} so it runs <em>before</em> the Spring
 * Security filter chain: a 401 or 403 produced by the security entry point must still
 * carry a trace id.
 *
 * <p>A caller-supplied {@code X-Trace-Id} is accepted only when it matches the same shape
 * the Python service accepts; anything else is replaced by a generated identifier rather
 * than echoed back, so a caller cannot inject arbitrary text into logs.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TraceIdFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String supplied = request.getHeader(TraceId.HEADER);
        String traceId = TraceId.isValid(supplied) ? supplied : TraceId.generate();

        TraceId.bind(traceId);
        response.setHeader(TraceId.HEADER, traceId);
        try {
            chain.doFilter(request, response);
        } finally {
            TraceId.clear();
        }
    }
}
