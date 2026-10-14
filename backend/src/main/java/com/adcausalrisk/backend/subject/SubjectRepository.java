package com.adcausalrisk.backend.subject;

import java.util.Collection;
import java.util.Optional;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import com.adcausalrisk.backend.subject.entity.Subject;

/**
 * Data access for the {@code subject} table.
 */
@Repository
public interface SubjectRepository extends JpaRepository<Subject, Long> {

    /**
     * Looks up a subject by its natural key. The DDL enforces a UNIQUE constraint
     * on {@code subject_code}, so at most one row matches.
     */
    Optional<Subject> findBySubjectCode(String subjectCode);

    boolean existsBySubjectCode(String subjectCode);

    /**
     * Paged query for subjects whose {@code id} is in the given collection. Used
     * by {@link com.adcausalrisk.backend.subject.SubjectService} for DOCTOR and
     * PATIENT roles, where visible subjects are restricted to those the caller
     * has explicit permissions on.
     */
    Page<Subject> findByIdIn(Collection<Long> ids, Pageable pageable);
}