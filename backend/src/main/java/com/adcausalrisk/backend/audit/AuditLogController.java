package com.adcausalrisk.backend.audit;

import java.time.Instant;
import java.util.List;

import com.adcausalrisk.backend.audit.entity.AuditLog;
import com.adcausalrisk.backend.common.Envelope;
import com.adcausalrisk.backend.security.AppUserPrincipal;

import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** {@code GET /api/audit-logs} - administrator-only audit trail, newest first. */
@RestController
public class AuditLogController {

    private final AuditService auditService;

    public AuditLogController(AuditService auditService) {
        this.auditService = auditService;
    }

    /** {@code AuditEvent}. */
    public record AuditEventView(
            long id,
            Long actorId,
            String eventType,
            String traceId,
            String summary,
            Instant timestamp) {
    }

    @GetMapping("/api/audit-logs")
    public Envelope<List<AuditEventView>> list(Authentication authentication) {
        AppUserPrincipal principal = (AppUserPrincipal) authentication.getPrincipal();
        return Envelope.success(auditService.list(principal).stream()
                .map(AuditLogController::view)
                .toList());
    }

    private static AuditEventView view(AuditLog entry) {
        return new AuditEventView(
                entry.getId(),
                entry.getActorId(),
                entry.getEventType(),
                entry.getTraceId(),
                entry.getSummary(),
                entry.getOccurredAt());
    }
}
