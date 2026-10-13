package com.adcausalrisk.backend.security;

import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.adcausalrisk.backend.user.SysUser;
import com.adcausalrisk.backend.user.SysUserRepository;

/**
 * Loads an account and its roles for the authentication provider.
 *
 * <p>An unknown username and a disabled account are both refused. The exception message
 * deliberately does not repeat the submitted username, and
 * {@code DaoAuthenticationProvider} hides unknown-user failures as a bad credential, so the
 * caller of {@code POST /api/auth/login} learns nothing about which usernames exist.
 */
@Service
public class CustomUserDetailsService implements UserDetailsService {

    private final SysUserRepository users;

    public CustomUserDetailsService(SysUserRepository users) {
        this.users = users;
    }

    @Override
    @Transactional(readOnly = true)
    public UserDetails loadUserByUsername(String username) throws UsernameNotFoundException {
        SysUser user = users.findByUsername(username)
                .orElseThrow(() -> new UsernameNotFoundException("no account with the submitted username"));

        return new AppUserPrincipal(
                user.getId(),
                user.getUsername(),
                user.getPasswordHash(),
                user.getRoleCodes(),
                user.getStatus() == SysUser.Status.ACTIVE);
    }
}
