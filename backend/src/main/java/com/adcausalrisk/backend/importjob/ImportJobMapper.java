package com.adcausalrisk.backend.importjob;

import java.util.List;

import com.adcausalrisk.backend.importjob.dto.ImportJobErrorView;
import com.adcausalrisk.backend.importjob.dto.ImportJobView;
import com.adcausalrisk.backend.importjob.entity.DataImportJob;

/**
 * Hand-written entity to DTO conversion, following the same style as
 * {@code SubjectMapper} and {@code VisitMapper}: a plain static utility, no mapping library.
 */
public final class ImportJobMapper {

    private ImportJobMapper() {
        // utility class - no instances
    }

    /**
     * @param errors already deserialised from {@code error_report_json}; the mapper stays free of
     *               Jackson so it can remain a static, dependency-free converter.
     */
    public static ImportJobView toView(DataImportJob job, List<ImportJobErrorView> errors) {
        return new ImportJobView(
                job.getId(),
                job.getStatus().name(),
                job.getDataVersion(),
                job.getTotalRows(),
                job.getValidRows(),
                job.getInvalidRows(),
                errors);
    }
}
