package com.adcausalrisk.backend.subject;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import com.adcausalrisk.backend.subject.entity.SubjectPermission;

/**
 * Data access for the {@code subject_permission} table.
 *
 * <p>The table has a UNIQUE constraint on {@code (subject_id, user_id,
 * permission_type)}, so a user may hold multiple permission types on the same
 * subject - but {@link #findDistinctSubjectIdByUserId} collapses them to a
 * single {@code subjectId}.
 */
@Repository
public interface SubjectPermissionRepository extends JpaRepository<SubjectPermission, Long> {

    /**
     * Returns every subject the given user has any permission on, with
     * duplicates collapsed. One row in {@code subject_permission} (any
     * permission_type) is enough for the subject to count as visible.
     *
     * <p>Written explicitly with {@code @Query} because the corresponding
     * derived-method name {@code findDistinctSubjectIdByUserId} triggers a
     * Hibernate 6 type-mismatch bug (returns the entity instead of the
     * primitive when the attribute is a simple {@code Long}).
     */
    @Query("SELECT DISTINCT sp.subjectId FROM SubjectPermission sp WHERE sp.userId = :userId")
    List<Long> findDistinctSubjectIdByUserId(@Param("userId") Long userId);
}