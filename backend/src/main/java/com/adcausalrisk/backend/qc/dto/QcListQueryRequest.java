package com.adcausalrisk.backend.qc.dto;

import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/**
 * Query parameters for the QC audit list endpoint.
 *
 * <p>All three filters are optional — the repository's {@code findJoined} method
 * treats {@code null} or blank values as "no filter". Both subject columns are
 * used with {@code LIKE '%?%'} so the frontend can offer a search box.
 *
 * <p>{@code page} / {@code pageSize} live on the controller method signature (int primitives,
 * defaulting to 1 and 20) rather than here — this record only captures filter state.
 */
public record QcListQueryRequest(

        @Size(max = 100, message = "subjectCode 长度不能超过 100")
        String subjectCode,

        @Size(max = 100, message = "subjectAlias 长度不能超过 100")
        String subjectAlias,

        @Pattern(regexp = "|PENDING|APPROVED|REJECTED",
                message = "status 只能是 PENDING / APPROVED / REJECTED 或留空")
        String status
) {
}