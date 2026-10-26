package com.adcausalrisk.backend.qc.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/**
 * Request body for {@code POST /api/qc-audit/{id}/submit} — the auditor submits
 * a decision on a previously-created PENDING row.
 *
 * <p>{@code abnormalItems} is optional: APPROVED rows often have no anomalies to record.
 * When present it must be a JSON array string (validated at runtime by the service),
 * e.g. {@code ["mmse score 35 exceeds valid range 0-30"]}.
 *
 * <p>{@code auditComment} is always required because every decision needs a human note
 * explaining why — APPROVED rows say "数据核对无误", REJECTED rows say what was wrong.
 */
public record QcSubmitRequest(

        @NotBlank(message = "status 不能为空")
        @Pattern(regexp = "APPROVED|REJECTED",
                message = "status 只能是 APPROVED 或 REJECTED")
        String status,

        /**
         * Optional JSON array of anomaly details. Leave null/empty when the auditor
         * approves without seeing issues. A string literal is used here (not
         * {@code List<String>}) because the entity stores it as TEXT to avoid
         * MySQL-specific JSON column types.
         */
        @Size(max = 4000, message = "abnormalItems 长度不能超过 4000")
        String abnormalItems,

        @NotBlank(message = "auditComment 不能为空")
        @Size(max = 2000, message = "auditComment 长度不能超过 2000")
        String auditComment
) {
}