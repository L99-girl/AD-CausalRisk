package com.adcausalrisk.backend.importjob;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import com.adcausalrisk.backend.importjob.entity.DataImportJob;

import jakarta.persistence.LockModeType;

/** Data access for the {@code data_import_job} table. */
@Repository
public interface DataImportJobRepository extends JpaRepository<DataImportJob, Long> {

    /**
     * Reads one job while holding a write lock on its row.
     *
     * <p>{@code commit} must use this instead of {@link #findById}: without the lock two
     * concurrent commits both read {@code PREVIEW_READY}, both pass the state check and both
     * insert the rows - the second one duplicates them, which stays invisible for features
     * because {@code subject_feature} has no unique constraint. The lock serialises the pair: the
     * second request blocks until the first commits and then sees {@code COMMITTED}, so it is
     * refused with 400 instead of inserting a second copy.
     *
     * <p>Requires an active transaction, which {@code commit} provides.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select j from DataImportJob j where j.id = :id")
    Optional<DataImportJob> findByIdForUpdate(@Param("id") Long id);
}
