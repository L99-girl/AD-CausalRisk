package com.adcausalrisk.backend.importjob;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import com.adcausalrisk.backend.importjob.entity.IdempotencyRecord;

/**
 * Data access for {@code idempotency_record}.
 *
 * <p>The lookup key is exactly the DDL's unique key, so a found row always identifies one prior
 * request from the same user.
 */
@Repository
public interface IdempotencyRecordRepository extends JpaRepository<IdempotencyRecord, Long> {

    Optional<IdempotencyRecord> findByUserIdAndOperationAndIdempotencyKey(
            Long userId, String operation, String idempotencyKey);
}
