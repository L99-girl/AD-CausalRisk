package com.adcausalrisk.backend.importjob.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * One recorded {@code Idempotency-Key}, from the baseline {@code idempotency_record} table.
 *
 * <p>{@code uq_idempotency_record} is {@code UNIQUE (user_id, operation, idempotency_key)}, and
 * that constraint - not a pre-check - is what makes a concurrent retry safe: the second writer
 * loses the insert and replays the winner's {@code resultId}.
 */
@Entity
@Table(name = "idempotency_record")
public class IdempotencyRecord {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "operation", nullable = false, length = 100)
    private String operation;

    @Column(name = "idempotency_key", nullable = false, length = 100)
    private String idempotencyKey;

    /** SHA-256 hex of the request payload; exactly 64 characters. */
    @Column(name = "request_digest", nullable = false, length = 64)
    private String requestDigest;

    /** The id of the resource the first request created. */
    @Column(name = "result_id")
    private Long resultId;

    protected IdempotencyRecord() {
        // for JPA
    }

    public IdempotencyRecord(Long userId, String operation, String idempotencyKey,
                             String requestDigest, Long resultId) {
        this.userId = userId;
        this.operation = operation;
        this.idempotencyKey = idempotencyKey;
        this.requestDigest = requestDigest;
        this.resultId = resultId;
    }

    public Long getId() {
        return id;
    }

    public Long getUserId() {
        return userId;
    }

    public String getOperation() {
        return operation;
    }

    public String getIdempotencyKey() {
        return idempotencyKey;
    }

    public String getRequestDigest() {
        return requestDigest;
    }

    public Long getResultId() {
        return resultId;
    }
}
