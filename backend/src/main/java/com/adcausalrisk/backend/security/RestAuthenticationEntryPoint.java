package com.adcausalrisk.backend.security;

import java.io.IOException;

import com.adcausalrisk.backend.common.ErrorCode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.stereotype.Component;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/**
 * Answers an unauthenticated request with HTTP 401 and the unified Envelope.
 *
 * <p>Without this, Spring Security would send a {@code WWW-Authenticate} challenge or an
 * empty body, and the contract's 401 response (an {@code Envelope} with a stable
 * {@code errorCode}) could not be produced.
 */
@Component
public class RestAuthenticationEntryPoint implements AuthenticationEntryPoint {

    private static final Logger log = LoggerFactory.getLogger(RestAuthenticationEntryPoint.class);

    private final ObjectMapper objectMapper;

    public RestAuthenticationEntryPoint(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public void commence(HttpServletRequest request, HttpServletResponse response,
                         AuthenticationException authenticationException) throws IOException {
        log.debug("refusing unauthenticated request to {}", request.getRequestURI(), authenticationException);
        SecurityEnvelopes.write(response, objectMapper, ErrorCode.UNAUTHENTICATED);
    }
}
