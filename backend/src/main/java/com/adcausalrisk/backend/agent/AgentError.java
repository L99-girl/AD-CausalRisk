package com.adcausalrisk.backend.agent;

import java.time.OffsetDateTime;

/**
 * Error body of the Python service (400/408/409/413/415/500/503), mirroring AgentError in
 * contracts/python-agent.openapi.json. All four properties are required.
 */
public record AgentError(String code, String message, String traceId, OffsetDateTime timestamp) {

    public static final String VALIDATION = "VALIDATION_400";
    public static final String CONTRACT_MISMATCH = "AGENT_CONTRACT_MISMATCH";
    public static final String RUN_ID_CONFLICT = "RUN_ID_CONFLICT";
    public static final String RUN_NOT_FOUND = "RUN_NOT_FOUND";
    public static final String PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE";
    public static final String UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE";
    public static final String ASSESSMENT_FAILED = "ASSESSMENT_FAILED";
    public static final String RUN_CAPACITY_REACHED = "RUN_CAPACITY_REACHED";
}