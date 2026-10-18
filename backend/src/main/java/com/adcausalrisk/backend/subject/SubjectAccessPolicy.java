package com.adcausalrisk.backend.subject;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

import org.springframework.stereotype.Component;

import com.adcausalrisk.backend.security.AppUserPrincipal;
import com.adcausalrisk.backend.subject.entity.Subject;

/**
 * Subject-level access control. Role-driven visible-range decisions that sit
 * between the Controller (which already ensures the caller is authenticated)
 * and the Repository.
 *
 * <p>The four roles resolve to two visibility tiers:
 * <ul>
 *     <li>{@code ADMIN}, {@code RESEARCHER} - every subject in the table is visible.</li>
 *     <li>{@code DOCTOR}, {@code PATIENT} - only subjects that appear in
 *         {@code subject_permission} for the caller's userId (any permission_type
 *         at all, VIEW / MANAGE / SUMMARY_READ, counts as a grant).</li>
 * </ul>
 *
 * <p>If a user carries multiple roles, the most permissive tier wins. So a
 * {@code RESEARCHER} who also has {@code DOCTOR} still sees every subject.
 */
@Component
public class SubjectAccessPolicy {

    /** Roles that bypass {@code subject_permission} entirely. */
    private static final Set<String> FULL_VIEW_ROLES = Set.of("ADMIN", "RESEARCHER");

    /** Roles allowed to create new subjects. */
    private static final Set<String> CREATOR_ROLES = Set.of("ADMIN", "RESEARCHER");

    /**
     * Roles allowed to receive raw visit scores (the full {@code visits} array of
     * {@code SubjectDetail}). Deliberately an allow-list: an unknown or future role must not
     * inherit access to raw scale scores by accident.
     */
    private static final Set<String> RAW_SCORE_ROLES = Set.of("ADMIN", "RESEARCHER", "DOCTOR");

    private final SubjectPermissionRepository permissionRepository;

    public SubjectAccessPolicy(SubjectPermissionRepository permissionRepository) {
        this.permissionRepository = permissionRepository;
    }

    /**
     * Whether the given principal may call {@code POST /api/subjects}.
     * Only {@code ADMIN} and {@code RESEARCHER} may create subjects.
     */
    public boolean canCreate(AppUserPrincipal principal) {
        return principal.roleCodes().stream().anyMatch(CREATOR_ROLES::contains);
    }

    /**
     * Whether the given principal bypasses {@code subject_permission} and may see
     * every subject in the table.
     */
    public boolean hasFullVisibility(AppUserPrincipal principal) {
        return principal.roleCodes().stream().anyMatch(FULL_VIEW_ROLES::contains);
    }

    /**
     * Whether the given principal may view (list-item or detail) the single subject.
     *
     * <p>For {@code ADMIN} / {@code RESEARCHER} this is always true. For
     * {@code DOCTOR} / {@code PATIENT} the method returns true only when
     * {@code subject_permission} contains at least one row pairing the subject
     * with the principal's userId.
     *
     * <p>Returns {@code false} (not an exception) when denied - the caller is
     * responsible for translating that into an {@code ACCESS_DENIED} (403)
     * response.
     */
    public boolean canView(AppUserPrincipal principal, Long subjectId) {
        if (hasFullVisibility(principal)) {
            return true;
        }
        List<Long> granted = permissionRepository.findDistinctSubjectIdByUserId(principal.userId());
        return granted.contains(subjectId);
    }

    /**
     * Whether the principal may receive raw visit scores - the {@code visits} array of
     * {@code SubjectDetail}, which carries {@code mmse}, {@code moca} and {@code cdrSb}.
     *
     * <p>This is a different question from {@link #canView}: that one answers "may this caller
     * see the subject at all", and a PATIENT holding {@code SUMMARY_READ} answers yes. That
     * grant is for the patient-facing summary, not for raw scale scores, so a PATIENT may read
     * the subject while receiving an empty {@code visits} array.
     *
     * <p>An allow-list rather than a "deny PATIENT" check, so an unknown or future role is
     * refused by default. Multi-role accounts follow the same "most permissive tier wins" rule
     * as {@link #hasFullVisibility}: a DOCTOR who also holds PATIENT still sees the scores.
     */
    public boolean canReadRawScores(AppUserPrincipal principal) {
        return principal.roleCodes().stream().anyMatch(RAW_SCORE_ROLES::contains);
    }

    /**
     * Filters a raw list of subjects down to those the principal may see.
     *
     * <p>{@code ADMIN} / {@code RESEARCHER} receive the input list unchanged.
     * Other roles receive only subjects whose {@code id} appears in
     * {@code subject_permission} for their userId.
     *
     * <p><b>Important:</b> callers must filter <i>before</i> paging. Paging on
     * the raw table then filtering would produce wrong {@code total} values
     * and pages that return fewer than {@code pageSize} items.
     */
    public List<Subject> filterVisible(AppUserPrincipal principal, List<Subject> subjects) {
        if (hasFullVisibility(principal)) {
            return subjects;
        }
        Set<Long> granted = new HashSet<>(permissionRepository.findDistinctSubjectIdByUserId(principal.userId()));
        return subjects.stream()
                .filter(s -> granted.contains(s.getId()))
                .toList();
    }

    /**
     * Returns the set of subject IDs the principal is allowed to see -
     * <b>only meaningful when {@link #hasFullVisibility} returns {@code false}</b>.
     *
     * <p>When {@code hasFullVisibility} is {@code true}, callers must ignore this
     * result and query the whole table instead. When {@code false}, the returned
     * set (which may itself be empty if the caller has zero grants) is the exact
     * pagination window that must be used.
     *
     * <p>This deliberately avoids the ambiguity of the older design where an empty
     * set meant two opposite things ("see everything" vs. "see nothing").
     */
    public Set<Long> grantedSubjectIds(AppUserPrincipal principal) {
        return new HashSet<>(permissionRepository.findDistinctSubjectIdByUserId(principal.userId()));
    }
}