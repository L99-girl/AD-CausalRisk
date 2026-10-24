package com.adcausalrisk.backend.importjob;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import com.adcausalrisk.backend.common.BusinessException;
import com.adcausalrisk.backend.importjob.dto.ImportJobView;
import com.adcausalrisk.backend.security.AppUserPrincipal;
import com.adcausalrisk.backend.subject.SubjectRepository;
import com.adcausalrisk.backend.subject.entity.Subject;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

/**
 * Proves the commit is serialised by the row lock.
 *
 * <p>Deliberately <b>not</b> {@code @Transactional}: each thread needs its own committed
 * transaction, otherwise the second one could not see (or contend for) the job row at all. That
 * also means the rows this test writes survive until {@link #cleanUp()} removes them, because the
 * H2 database is shared by every context in the run.
 *
 * <p>The invariant is what matters: two simultaneous commits must insert the rows exactly once.
 * Subjects and visits are protected by unique constraints, but {@code subject_feature} has none,
 * so a lost lock shows up here as four feature rows instead of two - or as a 500 from the
 * constraint violation.
 */
@SpringBootTest
@ActiveProfiles("test")
class ImportJobCommitConcurrencyTest {

    private static final String SUBJECT_CODE = "DEMO-880";

    private static final String IDEMPOTENCY_KEY = "concurrency-commit-key";

    @Autowired
    private ImportJobService importJobService;

    @Autowired
    private DataImportJobRepository jobRepository;

    @Autowired
    private SubjectRepository subjectRepository;

    @Autowired
    private JdbcTemplate jdbc;

    private Long jobId;

    @AfterEach
    void cleanUp() {
        jdbc.update("DELETE FROM subject_feature WHERE subject_id IN"
                + " (SELECT id FROM subject WHERE subject_code = ?)", SUBJECT_CODE);
        jdbc.update("DELETE FROM idempotency_record WHERE idempotency_key = ?", IDEMPOTENCY_KEY);
        if (jobId != null) {
            jobRepository.deleteById(jobId);
            jobId = null;
        }
        subjectRepository.findBySubjectCode(SUBJECT_CODE)
                .ifPresent(subject -> subjectRepository.deleteById(subject.getId()));
    }

    @Test
    void twoConcurrentCommitsInsertTheRowsOnlyOnce() throws Exception {
        Subject subject = subjectRepository.save(new Subject(SUBJECT_CODE, "并发提交测试档案",
                Subject.Status.ACTIVE, "demo-concurrency", Instant.now()));
        AppUserPrincipal admin = admin();

        String csv = "subjectCode,featureName,featureValue,recordedAt,unit\n"
                + SUBJECT_CODE + ",APOE_E4_COUNT,1,2025-01-01,count\n"
                + SUBJECT_CODE + ",MRI_HIPPOCAMPUS_L,0.5,2025-01-01,normalized\n";
        jobId = importJobService.preview(admin, IDEMPOTENCY_KEY,
                csv.getBytes(StandardCharsets.UTF_8)).jobId();

        List<Object> outcomes = commitTwice();
        long committed = outcomes.stream().filter(ImportJobView.class::isInstance).count();

        assertThat(committed).as("exactly one commit may succeed").isEqualTo(1);
        assertThat(outcomes).as("the loser is refused with a business failure, never a 500")
                .allSatisfy(outcome -> assertThat(outcome)
                        .isInstanceOfAny(ImportJobView.class, BusinessException.class));
        assertThat(outcomes).anySatisfy(outcome -> assertThat(outcome)
                .isInstanceOf(BusinessException.class));

        Integer features = jdbc.queryForObject(
                "SELECT COUNT(*) FROM subject_feature WHERE subject_id = ?", Integer.class,
                subject.getId());
        assertThat(features).as("the rows must be inserted exactly once").isEqualTo(2);
    }

    private List<Object> commitTwice() throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(2);
        CountDownLatch start = new CountDownLatch(1);
        try {
            List<Future<Object>> futures = new ArrayList<>(2);
            for (int i = 0; i < 2; i++) {
                futures.add(pool.submit(() -> {
                    start.await();
                    try {
                        return importJobService.commit(jobId, admin());
                    } catch (RuntimeException failure) {
                        return failure;
                    }
                }));
            }
            start.countDown();
            List<Object> outcomes = new ArrayList<>(2);
            for (Future<Object> future : futures) {
                outcomes.add(future.get(20, TimeUnit.SECONDS));
            }
            return outcomes;
        } finally {
            pool.shutdownNow();
        }
    }

    private AppUserPrincipal admin() {
        Long userId = jdbc.queryForObject(
                "SELECT id FROM sys_user WHERE username = 'admin'", Long.class);
        return new AppUserPrincipal(userId, "admin", "", List.of("ADMIN"), true);
    }
}
