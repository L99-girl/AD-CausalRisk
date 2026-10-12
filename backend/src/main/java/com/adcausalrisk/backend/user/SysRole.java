package com.adcausalrisk.backend.user;

import java.util.Objects;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * One of the four frozen contract roles: {@code ADMIN}, {@code RESEARCHER}, {@code DOCTOR},
 * {@code PATIENT}. Rows are reference data seeded by {@code V2__seed_synthetic_accounts.sql};
 * role management is not part of this PR, so this entity is read-only.
 *
 * <p>Equality uses {@code role_code} (the natural key) because roles are stored in a
 * {@code Set} on the user and the immutable code is stable across persistence contexts.
 */
@Entity
@Table(name = "sys_role")
public class SysRole {

    @Id
    @Column(name = "id", nullable = false)
    private Long id;

    @Column(name = "role_code", nullable = false, length = 20, unique = true)
    private String roleCode;

    protected SysRole() {
        // for JPA
    }

    public Long getId() {
        return id;
    }

    public String getRoleCode() {
        return roleCode;
    }

    @Override
    public boolean equals(Object other) {
        return other instanceof SysRole role && roleCode != null && roleCode.equals(role.roleCode);
    }

    @Override
    public int hashCode() {
        return Objects.hashCode(roleCode);
    }
}
