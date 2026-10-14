package com.adcausalrisk.backend.subject.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;

/**
 * Request body for {@code POST /api/subjects}. Maps the frozen contract schema
 * {@code SubjectCreate} exactly - no extra fields, no fewer.
 *
 * <p>{@code status} is optional in the contract; {@code SubjectService} defaults
 * it to {@code ACTIVE} when absent.
 */
public record SubjectCreateRequest(

        @NotBlank(message = "subjectCode 不能为空")
        @Pattern(regexp = "^DEMO-[A-Za-z0-9-]{1,45}$",
                message = "subjectCode 格式无效，须匹配 DEMO-[A-Za-z0-9-]{1,45}")
        String subjectCode,

        @NotBlank(message = "alias 不能为空")
        String alias,

        String status
) {
}