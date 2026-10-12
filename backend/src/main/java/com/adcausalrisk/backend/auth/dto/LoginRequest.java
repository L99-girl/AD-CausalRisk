package com.adcausalrisk.backend.auth.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * Body of {@code POST /api/auth/login}, matching the contract's {@code Login} schema.
 *
 * <p>The contract marks both properties required and sets no limits; the length limits are
 * ours and mirror the {@code sys_user.username} column, so an oversized credential never
 * reaches the password encoder.
 */
public record LoginRequest(
        @NotBlank @Size(max = 50) String username,
        @NotBlank @Size(max = 100) String password) {
}
