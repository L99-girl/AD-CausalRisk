package com.adcausalrisk.backend.audit.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * One auditable event (V1 {@code audit_log}, FR-AUDIT-01).
 *
 * <p>{@code actorId} is nullable on purpose: a refused login for an unknown username has no user
 * row, and {@code occurredAt} is the contract's {@code AuditEvent.timestamp}.
 */
@Entity
@Table(name = "audit_log")
public class AuditLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false)
    private Long id;

    @Column(name = "actor_id")
    private Long actorId;

    @Column(name = "event_type", nullable = false, length = 50)
    private String eventType;

    @Column(name = "trace_id", nullable = false, length = 64)
    private String traceId;

    @Column(name = "summary", nullable = false, length = 500)
    private String summary;

    @Column(name = "occurred_at", nullable = false)
    private Instant occurredAt;

    protected AuditLog() {
        // for JPA
    }

    public AuditLog(Long actorId, String eventType, String traceId, String summary, Instant occurredAt) {
        this.actorId = actorId;
        this.eventType = eventType;
        this.traceId = traceId;
        this.summary = summary;
        this.occurredAt = occurredAt;
    }

    public Long getId() {
        return id;
    }

    public Long getActorId() {
        return actorId;
    }

    public String getEventType() {
        return eventType;
    }

    public String getTraceId() {
        return traceId;
    }

    public String getSummary() {
        return summary;
    }

    public Instant getOccurredAt() {
        return occurredAt;
    }
}
