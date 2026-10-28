package com.adcausalrisk.backend.audit;

import java.util.List;

import com.adcausalrisk.backend.audit.entity.AuditLog;

import org.springframework.data.jpa.repository.JpaRepository;

public interface AuditLogRepository extends JpaRepository<AuditLog, Long> {

    List<AuditLog> findAllByOrderByOccurredAtDescIdDesc();

    List<AuditLog> findByActorIdOrderByOccurredAtDescIdDesc(Long actorId);
}
