package com.adcausalrisk.backend.security;

import java.util.Collection;
import java.util.List;

import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetails;

/**
 * The authenticated principal: exactly the fields the session and the responses need, and
 * deliberately not a JPA entity, because {@code spring.jpa.open-in-view} is false and a
 * detached entity must not leak out of the transaction that loaded it.
 *
 * <p>{@code passwordHash} is carried because {@link UserDetails} requires
 * {@link #getPassword()} during authentication. {@link AuthService} stores a copy with the
 * hash erased in the session, so later requests never hold the credential material.
 */
public record AppUserPrincipal(
        long userId,
        String username,
        String passwordHash,
        List<String> roleCodes,
        boolean enabled) implements UserDetails {

    public AppUserPrincipal {
        roleCodes = List.copyOf(roleCodes);
    }

    /** Same principal without credential material, for storage in the session. */
    public AppUserPrincipal withPasswordErased() {
        return new AppUserPrincipal(userId, username, "", roleCodes, enabled);
    }

    @Override
    public Collection<? extends GrantedAuthority> getAuthorities() {
        return roleCodes.stream().map(role -> new SimpleGrantedAuthority("ROLE_" + role)).toList();
    }

    @Override
    public String getPassword() {
        return passwordHash;
    }

    @Override
    public String getUsername() {
        return username;
    }

    @Override
    public boolean isAccountNonExpired() {
        return true;
    }

    @Override
    public boolean isAccountNonLocked() {
        return true;
    }

    @Override
    public boolean isCredentialsNonExpired() {
        return true;
    }

    @Override
    public boolean isEnabled() {
        return enabled;
    }
}
