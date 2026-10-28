package com.adcausalrisk.backend.subject.dto;

import java.math.BigDecimal;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;

/**
 * Request body for {@code POST /api/subjects/{subjectId}/features}: the contract's {@code Feature}
 * schema, one row per call. {@code featureValue} is nullable (a missing measurement is valid);
 * the enum and cross-field rules (APOE must be the integer count, MRI must be normalized in [0,1])
 * are enforced in {@code FeatureService}, where they can name the offending field.
 */
public record FeatureCreateRequest(
        @NotBlank(message = "featureName 不能为空") String featureName,
        BigDecimal featureValue,
        @NotBlank(message = "recordedAt 不能为空")
        @Pattern(regexp = "^\\d{4}-\\d{2}-\\d{2}$", message = "格式须为 yyyy-MM-dd")
        String recordedAt,
        @NotBlank(message = "unit 不能为空") String unit) {
}
