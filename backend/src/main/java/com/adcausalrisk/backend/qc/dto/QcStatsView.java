package com.adcausalrisk.backend.qc.dto;

/**
 * Dashboard aggregate for the QC module: one count per status bucket.
 *
 * <p>The service computes this from
 * {@link com.adcausalrisk.backend.qc.QcAuditRecordRepository#groupByStatus()} and
 * always includes all three buckets (defaulting to zero), so the frontend never
 * sees a missing key.
 */
public record QcStatsView(
        long pendingCount,
        long approvedCount,
        long rejectedCount
) {
}