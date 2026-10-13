package com.adcausalrisk.backend.auth.dto;

import java.util.List;

/**
 * Body of a successful {@code POST /api/auth/login} and of {@code GET /api/me}, matching the
 * contract's {@code CurrentUser} schema.
 *
 * <p>Carries no credential material: the principal's password hash is never mapped here.
 * {@code roles} and {@code menus} are delivered in a deterministic (sorted) order, which
 * consumers must treat as unspecified.
 */
public record CurrentUserView(
        long id,
        String username,
        List<String> roles,
        List<String> menus) {
}
