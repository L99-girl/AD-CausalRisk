package com.adcausalrisk.backend.user;

import java.time.Instant;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.JoinTable;
import jakarta.persistence.ManyToMany;
import jakarta.persistence.Table;

/**
 * An account from {@code sys_user}. Only synthetic course accounts exist (see
 * {@code V2__seed_synthetic_accounts.sql}).
 *
 * <p>The password is stored as a BCrypt hash and is never exposed: this entity is never
 * returned from a controller, and {@code CurrentUser} carries no password field.
 */
@Entity
@Table(name = "sys_user")
public class SysUser {

    public enum Status {
        ACTIVE,
        DISABLED
    }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false)
    private Long id;

    @Column(name = "username", nullable = false, length = 50, unique = true)
    private String username;

    @Column(name = "password_hash", nullable = false, length = 100)
    private String passwordHash;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private Status status;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    /**
     * EAGER on purpose: every authenticated request needs the role codes to build
     * {@code CurrentUser.roles} and the role menus, {@code spring.jpa.open-in-view} is false,
     * and a lazily loaded collection could not be read after the repository call returned.
     * The join table holds at most four rows per account.
     */
    @ManyToMany(fetch = FetchType.EAGER)
    @JoinTable(name = "user_role",
            joinColumns = @JoinColumn(name = "user_id"),
            inverseJoinColumns = @JoinColumn(name = "role_id"))
    private Set<SysRole> roles = new LinkedHashSet<>();

    protected SysUser() {
        // for JPA
    }

    public Long getId() {
        return id;
    }

    public String getUsername() {
        return username;
    }

    public String getPasswordHash() {
        return passwordHash;
    }

    public Status getStatus() {
        return status;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    /**
     * The account's role codes in a deterministic (alphabetical) order. Callers must treat
     * the order as unspecified - it only exists so responses and tests are stable.
     */
    public List<String> getRoleCodes() {
        return roles.stream().map(SysRole::getRoleCode).sorted().toList();
    }
}
