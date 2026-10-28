package com.adcausalrisk.backend.qualitycheck;

import com.adcausalrisk.backend.common.Envelope;
import com.adcausalrisk.backend.qualitycheck.QualityCheckService.QualityCheckResult;
import com.adcausalrisk.backend.security.AppUserPrincipal;

import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code POST /api/subjects/{subjectId}/quality-checks} - the contract's subject-level quality
 * check. Kept in its own controller so the {@code /api/subjects} mappings stay about the subject
 * resource itself.
 */
@RestController
@RequestMapping("/api/subjects/{subjectId}/quality-checks")
public class QualityCheckController {

    private final QualityCheckService qualityCheckService;

    public QualityCheckController(QualityCheckService qualityCheckService) {
        this.qualityCheckService = qualityCheckService;
    }

    @PostMapping
    public Envelope<QualityCheckResult> check(
            @PathVariable Long subjectId, Authentication authentication) {
        AppUserPrincipal principal = (AppUserPrincipal) authentication.getPrincipal();
        return Envelope.success(qualityCheckService.check(subjectId, principal));
    }
}
