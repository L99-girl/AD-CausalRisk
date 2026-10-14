package com.adcausalrisk.backend.subject.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * A row from {@code subject_permission}: grants a user a specific permission type
 * on a specific subject.
 *
 * <p>The DDL CHECK constrains {@code permission_type} to the three values below, and
 * a UNIQUE constraint on {@code (subject_id, user_id, permission_type} prevents
 * duplicate grants.
 */
@Entity
@Table(name = "subject_permission")
public class SubjectPermission {

    public enum PermissionType {
        VIEW,
        MANAGE,
        SUMMARY_READ
    }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false)
    private Long id;

    @Column(name = "subject_id", nullable = false)
    private Long subjectId;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Enumerated(EnumType.STRING)
    @Column(name = "permission_type", nullable = false, length = 30)
    private PermissionType permissionType;

    protected SubjectPermission() {
        // for JPA
    }

    public SubjectPermission(Long subjectId, Long userId, PermissionType permissionType) {
        this.subjectId = subjectId;
        this.userId = userId;
        this.permissionType = permissionType;
    }

    public Long getId() {
        return id;
    }

    public Long getSubjectId() {
        return subjectId;
    }

    public Long getUserId() {
        return userId;
    }

    public PermissionType getPermissionType() {
        return permissionType;
    }
}