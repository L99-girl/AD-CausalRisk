package com.adcausalrisk.backend.audit;

import com.adcausalrisk.backend.audit.annotation.AuditLog;
import com.adcausalrisk.backend.security.AppUserPrincipal;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;

/**
 * Writes one audit row after a method annotated with {@link AuditLog} returns successfully.
 *
 * <p>Failure is recorded by the surrounding exception handler instead: an audited operation that
 * throws did not happen, and the failed path already leaves its own trace. The row is written in
 * its own transaction, so it survives even when the business transaction rolls back afterwards.
 */
@Aspect
@Component
public class AuditLogAspect {

    private final AuditService auditService;

    public AuditLogAspect(AuditService auditService) {
        this.auditService = auditService;
    }

    @Around("@annotation(auditLog)")
    public Object recordAfterSuccess(ProceedingJoinPoint joinPoint, AuditLog auditLog) throws Throwable {
        Object result = joinPoint.proceed();
        String summary = auditLog.summary().isBlank()
                ? joinPoint.getSignature().toShortString()
                : auditLog.summary();
        auditService.recordQuietly(currentActorId(), auditLog.eventType(), summary);
        return result;
    }

    private static Long currentActorId() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.getPrincipal() instanceof AppUserPrincipal principal) {
            return principal.userId();
        }
        return null;
    }
}
