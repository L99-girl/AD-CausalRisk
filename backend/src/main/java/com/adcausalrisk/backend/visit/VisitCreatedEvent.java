package com.adcausalrisk.backend.visit;

/**
 * Fired <b>after</b> {@code VisitService.createVisit} commits the new row.
 *
 * <p>Only carries the row PK and the triggering operator — the event listener must re-load
 * the Visit from the database (its Hibernate session is already closed by the time
 * {@code @TransactionalEventListener(phase = AFTER_COMMIT)} runs, so passing the entity
 * directly would hand a detached object to the listener).
 *
 * <p>Designed to be consumed by the QC audit module, which needs its own independent
 * transaction: {@code AFTER_COMMIT} + {@code REQUIRES_NEW} guarantees that a QC failure
 * can never undo a visit that was already durably written.
 */
public record VisitCreatedEvent(Long visitId, Long operatorId) {
}