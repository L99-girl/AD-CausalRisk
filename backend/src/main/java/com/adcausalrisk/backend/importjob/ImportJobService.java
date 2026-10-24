package com.adcausalrisk.backend.importjob;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Types;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import com.adcausalrisk.backend.common.BusinessException;
import com.adcausalrisk.backend.common.ErrorCode;
import com.adcausalrisk.backend.importjob.csv.CsvImportParser;
import com.adcausalrisk.backend.importjob.csv.ImportLookups;
import com.adcausalrisk.backend.importjob.csv.ImportRow;
import com.adcausalrisk.backend.importjob.csv.ImportTable;
import com.adcausalrisk.backend.importjob.csv.ParsedImport;
import com.adcausalrisk.backend.importjob.csv.RowIssue;
import com.adcausalrisk.backend.importjob.dto.ImportJobErrorView;
import com.adcausalrisk.backend.importjob.dto.ImportJobView;
import com.adcausalrisk.backend.importjob.entity.DataImportJob;
import com.adcausalrisk.backend.importjob.entity.IdempotencyRecord;
import com.adcausalrisk.backend.security.AppUserPrincipal;
import com.adcausalrisk.backend.subject.SubjectAccessPolicy;
import com.adcausalrisk.backend.subject.SubjectRepository;
import com.adcausalrisk.backend.subject.entity.Subject;
import com.adcausalrisk.backend.visit.VisitRepository;
import com.adcausalrisk.backend.visit.entity.Visit;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.BatchPreparedStatementSetter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Business logic for the three import endpoints.
 *
 * <p>Lifecycle: {@code POST /api/import-jobs} validates the upload and stores the result and the
 * uploaded text (a preview); {@code POST /api/import-jobs/{jobId}/commit} re-parses that stored
 * text and inserts the valid rows. Nothing is written to {@code subject} / {@code visit} /
 * {@code subject_feature} until the commit, and rejected rows are never inserted.
 *
 * <p><b>Why the commit re-parses instead of trusting a second upload.</b> The upload is not kept
 * in memory between the two calls, so the only way to insert exactly what was previewed is to
 * re-read what was stored. If the re-parse disagrees with the preview's {@code validRows}, the
 * database changed underneath (a subject was deleted, a visit code was added) and the request is
 * refused instead of inserting a different set than the caller approved.
 *
 * <p><b>Idempotency.</b> {@code Idempotency-Key} is recorded per user and operation in
 * {@code idempotency_record} together with a SHA-256 digest of the upload. Replaying the same key
 * with the same bytes returns the original job; the same key with different bytes is refused.
 * The uniqueness is enforced by {@code uq_idempotency_record}, so two concurrent retries cannot
 * both create a job - the loser replays the winner instead of failing with a 500.
 */
@Service
public class ImportJobService {

    private static final String OPERATION = "IMPORT_JOB_PREVIEW";

    private static final Logger log = LoggerFactory.getLogger(ImportJobService.class);

    private static final TypeReference<List<ImportJobErrorView>> ERROR_LIST =
            new TypeReference<>() {
            };

    private final DataImportJobRepository jobRepository;

    private final IdempotencyRecordRepository idempotencyRepository;

    private final SubjectRepository subjectRepository;

    private final VisitRepository visitRepository;

    private final JdbcTemplate jdbcTemplate;

    private final SubjectAccessPolicy accessPolicy;

    private final CsvImportParser parser;

    private final ObjectMapper objectMapper;

    /** The business-day clock; "today" must not depend on the host's zone. */
    private final Clock clock;

    private final TransactionTemplate transactionTemplate;

    public ImportJobService(DataImportJobRepository jobRepository,
                            IdempotencyRecordRepository idempotencyRepository,
                            SubjectRepository subjectRepository,
                            VisitRepository visitRepository,
                            JdbcTemplate jdbcTemplate,
                            SubjectAccessPolicy accessPolicy,
                            CsvImportParser parser,
                            ObjectMapper objectMapper,
                            Clock clock,
                            PlatformTransactionManager transactionManager) {
        this.jobRepository = jobRepository;
        this.idempotencyRepository = idempotencyRepository;
        this.subjectRepository = subjectRepository;
        this.visitRepository = visitRepository;
        this.jdbcTemplate = jdbcTemplate;
        this.accessPolicy = accessPolicy;
        this.parser = parser;
        this.objectMapper = objectMapper;
        this.clock = clock;
        this.transactionTemplate = new TransactionTemplate(transactionManager);
    }

    /**
     * Validates an uploaded CSV and records a preview.
     *
     * <p>Importing is the same privilege as creating a subject, so it reuses
     * {@link SubjectAccessPolicy#canCreate}: importing writes subjects and their clinical data,
     * and inventing a second role list would let the two drift apart.
     */
    public ImportJobView preview(AppUserPrincipal principal, String idempotencyKey, byte[] bytes) {
        // The contract declares Idempotency-Key as 1-100 characters, and
        // idempotency_record.idempotency_key is VARCHAR(100). Without this check an over-long key
        // fails inside the INSERT, which surfaces as a constraint violation - and the replay
        // lookup below cannot find a record for it, so the caller would get a 500.
        if (idempotencyKey == null || idempotencyKey.isBlank() || idempotencyKey.length() > 100) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR,
                    "Idempotency-Key 长度须为 1-100");
        }
        if (!accessPolicy.canCreate(principal)) {
            throw new BusinessException(ErrorCode.ACCESS_DENIED, "无权导入数据");
        }
        if (bytes.length == 0) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR, "上传文件为空");
        }

        String digest = sha256(bytes);
        Optional<IdempotencyRecord> prior =
                idempotencyRepository.findByUserIdAndOperationAndIdempotencyKey(
                        principal.userId(), OPERATION, idempotencyKey);
        if (prior.isPresent()) {
            return replay(prior.get(), digest);
        }

        String text = decodeUtf8(bytes);
        ParsedImport parsed = parser.parse(text, lookups(), LocalDate.now(clock));

        try {
            return transactionTemplate.execute(status -> persist(principal, idempotencyKey, digest,
                    text, parsed));
        } catch (DataIntegrityViolationException race) {
            // A concurrent request with the same key normally won the unique constraint and its
            // job is the answer for both callers. Anything else (a foreign key, a truncated key)
            // must still be a controlled refusal, never a 500 and never the raw exception.
            ImportJobView replayed = idempotencyRepository
                    .findByUserIdAndOperationAndIdempotencyKey(
                            principal.userId(), OPERATION, idempotencyKey)
                    .map(record -> replay(record, digest))
                    .orElse(null);
            if (replayed == null) {
                log.debug("preview insert failed without a recorded idempotency key", race);
                throw new BusinessException(ErrorCode.VALIDATION_ERROR, "导入请求处理冲突，请重试");
            }
            return replayed;
        }
    }

    /** One job, visible to its creator and to {@code ADMIN}. */
    @Transactional(readOnly = true)
    public ImportJobView get(Long jobId, AppUserPrincipal principal) {
        DataImportJob job = requireJob(jobId);
        requireReadable(job, principal);
        return toView(job);
    }

    /**
     * Inserts the rows the preview accepted and marks the job {@code COMMITTED}.
     *
     * <p>The contract gives {@code commit} no body, so it cannot carry a nonce: authorisation is
     * ownership plus status. A second commit finds {@code COMMITTED} and is refused with 400,
     * which is the only refusal the contract declares besides 401/403.
     */
    @Transactional
    public ImportJobView commit(Long jobId, AppUserPrincipal principal) {
        // The privilege is checked again here instead of being trusted from the preview: an
        // account demoted between preview and commit (RESEARCHER -> PATIENT) must not be able to
        // write the rows it prepared. Ownership alone is insufficient - the role is what
        // authorises writing subject/visit/feature data at all.
        if (!accessPolicy.canCreate(principal)) {
            throw new BusinessException(ErrorCode.ACCESS_DENIED, "无权导入数据");
        }
        // Taken under a write lock: two concurrent commits would otherwise both read
        // PREVIEW_READY and both insert, duplicating the rows that have no unique constraint
        // (features). The lock makes the second one block and then observe COMMITTED.
        DataImportJob job = jobRepository.findByIdForUpdate(jobId)
                .orElseThrow(() -> new BusinessException(ErrorCode.VALIDATION_ERROR,
                        "导入任务不存在"));
        requireReadable(job, principal);

        if (job.getStatus() != DataImportJob.Status.PREVIEW_READY) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR,
                    "当前状态不可入库: " + job.getStatus());
        }
        if (job.getPreviewCsv() == null) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR, "预览数据已失效，请重新预览");
        }

        ParsedImport reparsed = parser.parse(job.getPreviewCsv(), lookups(), LocalDate.now(clock));
        if (reparsed.table() != job.getImportType()) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR, "预览数据与任务类型不一致");
        }
        if (reparsed.validRows() != job.getValidRows()) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR,
                    "档案或访视数据在预览后已变化，请重新预览");
        }
        // The count catches most drift, but not a swap: one valid row can stop being valid while
        // a rejected one starts being valid, leaving validRows unchanged. The digest compares
        // the row set itself, so commit cannot insert a row the caller never saw as valid.
        // Jobs created before V6 carry no digest and fall back to the count check alone.
        if (job.getPreviewDigest() != null && !job.getPreviewDigest().equals(reparsed.digest())) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR,
                    "数据在预览后已变化，请重新预览");
        }

        insertRows(job, reparsed);
        job.markCommitted();
        return toView(job);
    }

    // ===================================================================
    // Internals
    // ===================================================================

    private ImportJobView persist(AppUserPrincipal principal, String idempotencyKey, String digest,
                                  String text, ParsedImport parsed) {
        DataImportJob job = new DataImportJob(principal.userId(), generateDataVersion(),
                Instant.now(), parsed.table(), parsed.totalRows(), parsed.validRows(),
                parsed.invalidRows(), writeErrors(parsed.issues()), text, digest,
                parsed.digest());
        DataImportJob saved = jobRepository.saveAndFlush(job);
        idempotencyRepository.saveAndFlush(
                new IdempotencyRecord(principal.userId(), OPERATION, idempotencyKey, digest,
                        saved.getId()));
        return toView(saved);
    }

    private ImportJobView replay(IdempotencyRecord record, String digest) {
        if (!record.getRequestDigest().equals(digest)) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR,
                    "Idempotency-Key 已用于另一个不同的上传，请使用新的 key");
        }
        Long resultId = record.getResultId();
        // A restored or partially recovered database can leave a record whose job row is gone.
        // findById(null) would raise IllegalArgumentException and become a 500, so a missing id
        // is reported the same way as a missing row.
        if (resultId == null) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR, "导入任务不存在");
        }
        DataImportJob job = jobRepository.findById(resultId)
                .orElseThrow(() -> new BusinessException(ErrorCode.VALIDATION_ERROR,
                        "导入任务不存在"));
        // Only the user who recorded the key may replay it. Without this check a restored record
        // pointing at another user's job (auto-increment reused after a restore) would disclose
        // that job through the replay path, which is the one read that does not go through
        // requireReadable.
        if (!job.getCreatedBy().equals(record.getUserId())) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR, "导入任务不存在");
        }
        return toView(job);
    }

    private void insertRows(DataImportJob job, ParsedImport parsed) {
        // saveAllAndFlush rather than saveAll: flushing here makes a constraint violation surface
        // as DataIntegrityViolationException inside this method (mapped to a 400), instead of at
        // transaction commit where it would arrive as TransactionSystemException and become a 500.
        switch (parsed.table()) {
            case SUBJECT -> subjectRepository.saveAllAndFlush(parsed.rows().stream()
                    // The job's data version labels the whole imported batch, so every subject
                    // from one upload shares it instead of each getting its own.
                    .map(row -> (ImportRow.Subject) row)
                    .map(row -> new Subject(row.subjectCode(), row.alias(),
                            Subject.Status.valueOf(row.status()), job.getDataVersion(),
                            Instant.now()))
                    .toList());
            case VISIT -> visitRepository.saveAllAndFlush(parsed.rows().stream()
                    .map(row -> (ImportRow.Visit) row)
                    // Constructing the entity (rather than inserting through JDBC) is what keeps
                    // the V4 invariant: raw_* keeps the submitted text and the DECIMAL columns
                    // get the rounded copy, both derived in one place.
                    .map(row -> new Visit(row.subjectId(), row.visitCode(), row.visitDate(),
                            row.mmse(), row.moca(), row.cdrSb()))
                    .toList());
            case FEATURE -> {
                // The feature module does not exist yet, so this insert names the columns
                // explicitly instead of claiming ownership of that table's entity mapping.
                List<ImportRow.Feature> features = parsed.rows().stream()
                        .map(row -> (ImportRow.Feature) row)
                        .toList();
                jdbcTemplate.batchUpdate(
                        "INSERT INTO subject_feature"
                                + " (subject_id, feature_name, feature_value, recorded_at, unit)"
                                + " VALUES (?, ?, ?, ?, ?)",
                        new BatchPreparedStatementSetter() {
                            @Override
                            public void setValues(PreparedStatement statement, int index)
                                    throws SQLException {
                                ImportRow.Feature row = features.get(index);
                                statement.setLong(1, row.subjectId());
                                statement.setString(2, row.featureName());
                                if (row.featureValue() == null) {
                                    // A missing value must be SQL NULL with an explicit type.
                                    // Binding it untyped (Types.NULL) works on H2 but is the one
                                    // path no MySQL run has exercised; DECIMAL matches the column
                                    // and is accepted by both drivers.
                                    statement.setNull(3, Types.DECIMAL);
                                } else {
                                    statement.setBigDecimal(3, row.featureValue());
                                }
                                statement.setDate(4, java.sql.Date.valueOf(row.recordedAt()));
                                statement.setString(5, row.unit());
                            }

                            @Override
                            public int getBatchSize() {
                                return features.size();
                            }
                        });
            }
        }
    }

    private DataImportJob requireJob(Long jobId) {
        return jobRepository.findById(jobId)
                .orElseThrow(() -> new BusinessException(ErrorCode.VALIDATION_ERROR,
                        "导入任务不存在"));
    }

    private void requireReadable(DataImportJob job, AppUserPrincipal principal) {
        boolean owner = job.getCreatedBy().equals(principal.userId());
        boolean admin = principal.roleCodes().contains("ADMIN");
        if (!owner && !admin) {
            throw new BusinessException(ErrorCode.ACCESS_DENIED, "无权访问该导入任务");
        }
    }

    private ImportLookups lookups() {
        return new RepositoryLookups(subjectRepository, visitRepository);
    }

    private ImportJobView toView(DataImportJob job) {
        return ImportJobMapper.toView(job, readErrors(job.getErrorReportJson()));
    }

    /**
     * Serialises the issues that go into {@code error_report_json}, capped at
     * {@link CsvImportParser#MAX_ISSUES}. The contract has no "truncated" flag, so the cap is
     * documented instead of modelled; the row counts stay exact either way.
     */
    private String writeErrors(List<RowIssue> issues) {
        List<ImportJobErrorView> capped = issues.stream()
                .limit(CsvImportParser.MAX_ISSUES)
                .map(issue -> new ImportJobErrorView(issue.rowNumber(), issue.field(),
                        issue.message()))
                .toList();
        try {
            return objectMapper.writeValueAsString(capped);
        } catch (JsonProcessingException exception) {
            throw new BusinessException(ErrorCode.INTERNAL_ERROR, null);
        }
    }

    private List<ImportJobErrorView> readErrors(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(json, ERROR_LIST);
        } catch (JsonProcessingException exception) {
            throw new BusinessException(ErrorCode.INTERNAL_ERROR, null);
        }
    }

    /** Same shape as the subject module's generator: satisfies {@code LIKE 'demo-%'}. */
    private static String generateDataVersion() {
        return "demo-" + UUID.randomUUID().toString().substring(0, 8);
    }

    private static String sha256(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is required by the JVM", exception);
        }
    }

    /** Strict UTF-8: a file that is not valid UTF-8 is refused instead of being mis-decoded. */
    private static String decodeUtf8(byte[] bytes) {
        try {
            return StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes))
                    .toString();
        } catch (CharacterCodingException exception) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR, "文件必须是 UTF-8 文本");
        }
    }

    /**
     * Repository-backed {@link ImportLookups}, memoising subject lookups so a file with many rows
     * for the same subject does not repeat the query.
     */
    private static final class RepositoryLookups implements ImportLookups {

        private final SubjectRepository subjects;

        private final VisitRepository visits;

        private final Map<String, Optional<Long>> subjectIds = new HashMap<>();

        private RepositoryLookups(SubjectRepository subjects, VisitRepository visits) {
            this.subjects = subjects;
            this.visits = visits;
        }

        @Override
        public Long subjectIdOf(String subjectCode) {
            return subjectIds.computeIfAbsent(subjectCode,
                    code -> subjects.findBySubjectCode(code).map(Subject::getId)).orElse(null);
        }

        @Override
        public boolean visitExists(Long subjectId, String visitCode) {
            return visits.existsBySubjectIdAndVisitCode(subjectId, visitCode);
        }
    }
}
