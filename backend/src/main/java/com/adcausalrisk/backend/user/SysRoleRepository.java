package com.adcausalrisk.backend.user;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

/**
 * Roles are loaded with the user for authentication, so the main code has no call site for
 * this repository yet; it is exercised by AuthApiTest and is the access point for the role
 * management work that FR-AUTH-02/03 still owes.
 */
public interface SysRoleRepository extends JpaRepository<SysRole, Long> {

    Optional<SysRole> findByRoleCode(String roleCode);
}
