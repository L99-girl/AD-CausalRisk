package com.adcausalrisk.backend.audit.annotation;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a controller method whose successful execution must leave an audit row.
 *
 * <p>Lives in the {@code annotation} package so the entity {@code AuditLog} keeps its natural
 * name; both are imported by {@code AuditLogAspect}.
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface AuditLog {

    /** Short machine-ish type recorded in {@code audit_log.event_type} (max 50). */
    String eventType();

    /** Human summary; when empty the aspect falls back to the method name. */
    String summary() default "";
}
