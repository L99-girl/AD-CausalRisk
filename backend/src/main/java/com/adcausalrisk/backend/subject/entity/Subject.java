package com.adcausalrisk.backend.subject.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * A single subject from the {@code subject} table.
 *
 * <p>The DDL CHECK constraint ensures {@code subject_code} matches the
 * {@code ^DEMO-[A-Za-z0-9-]{1,45}$} pattern, {@code status} is one of
 * {@code ACTIVE} or {@code ARCHIVED}, and {@code data_version} starts with
 * {@code demo-}. JPA is configured with {@code ddl-auto: validate} so any
 * mismatch between this entity and the baseline DDL fails fast at startup.
 */
@Entity
@Table(name = "subject")
public class Subject {

    public enum Status {
        ACTIVE,
        ARCHIVED
    }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false)
    private Long id;

    @Column(name = "subject_code", nullable = false, length = 50, unique = true)
    private String subjectCode;

    @Column(name = "alias", nullable = false, length = 100)
    private String alias;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private Status status;

    @Column(name = "data_version", nullable = false, length = 100)
    private String dataVersion;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected Subject() {
        // for JPA
    }

    public Subject(String subjectCode, String alias, Status status, String dataVersion, Instant createdAt) {
        this.subjectCode = subjectCode;
        this.alias = alias;
        this.status = status;
        this.dataVersion = dataVersion;
        this.createdAt = createdAt;
    }

    public Long getId() {
        return id;
    }

    public String getSubjectCode() {
        return subjectCode;
    }

    public String getAlias() {
        return alias;
    }

    public Status getStatus() {
        return status;
    }

    public String getDataVersion() {
        return dataVersion;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}