package com.adcausalrisk.backend.migration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.stream.Stream;

import javax.sql.DataSource;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

/**
 * Runs the real Flyway migrations on H2 (MySQL compatibility mode) and checks the
 * invariants the baseline schema is supposed to guarantee.
 *
 * <p>Runs on H2 only: this environment has no MySQL server and no Docker, so the
 * MySQL branch of V1/V2 stays unverified. See backend/README.md.
 */
@SpringBootTest
@ActiveProfiles("test")
@Transactional
class SchemaMigrationTest {

    /** Documented synthetic demo password. Must stay in sync with backend/README.md. */
    private static final String DEMO_PASSWORD = "DemoPass!2026";

    /** The 15 tables promised by docs/Design_Guide.md section 3. */
    private static final List<String> BASELINE_TABLES = List.of(
            "sys_user", "sys_role", "user_role",
            "subject", "subject_permission",
            "visit", "subject_feature",
            "data_import_job", "quality_check",
            "assessment_task", "idempotency_record", "risk_assessment",
            "assessment_review", "follow_up_plan", "audit_log");

    /** Flyway's own bookkeeping table; created by Flyway, not by V1. */
    private static final String FLYWAY_HISTORY_TABLE = "flyway_schema_history";

    /** Schemas that belong to the engine, not to this application. */
    private static final Set<String> SYSTEM_SCHEMAS = Set.of(
            "information_schema", "pg_catalog", "mysql", "performance_schema", "sys");

    @Autowired
    private JdbcTemplate jdbc;

    @Autowired
    private DataSource dataSource;

    @Test
    void flywayAppliedBothMigrations() {
        List<String> versions = jdbc.queryForList(
                "SELECT version FROM flyway_schema_history WHERE version IS NOT NULL ORDER BY installed_rank",
                String.class);

        assertThat(versions).containsExactly("1", "2");
    }

    @Test
    void baselineDefinesExactlyTheFifteenExpectedTables() throws SQLException {
        assertThat(BASELINE_TABLES).hasSize(15).doesNotHaveDuplicates();

        assertThat(applicationTables())
                .containsExactlyInAnyOrderElementsOf(
                        Stream.concat(BASELINE_TABLES.stream(), Stream.of(FLYWAY_HISTORY_TABLE)).toList());
    }

    @Test
    void seedCoversTheFourContractRoles() {
        List<String> roles = jdbc.queryForList("SELECT role_code FROM sys_role", String.class);

        assertThat(roles).containsExactlyInAnyOrder("ADMIN", "RESEARCHER", "DOCTOR", "PATIENT");
    }

    @Test
    void seedProvidesOneAccountPerRolePlusOneMultiRoleAccount() {
        List<String> grants = jdbc.query("""
                SELECT u.username, r.role_code
                FROM sys_user u
                JOIN user_role ur ON ur.user_id = u.id
                JOIN sys_role r ON r.id = ur.role_id
                """, (rs, rowNum) -> rs.getString(1) + ":" + rs.getString(2));

        assertThat(grants).containsExactlyInAnyOrder(
                "admin:ADMIN",
                "researcher:RESEARCHER",
                "doctor:DOCTOR",
                "patient:PATIENT",
                "research_doctor:RESEARCHER",
                "research_doctor:DOCTOR");
    }

    @Test
    void everySeededHashMatchesTheDocumentedDemoPassword() {
        List<String> hashes = jdbc.queryForList("SELECT password_hash FROM sys_user", String.class);

        assertThat(hashes).hasSize(5);

        BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();
        assertThat(hashes).allSatisfy(hash -> {
            assertThat(hash).matches("^\\$2[aby]\\$\\d{2}\\$.{53}$");
            assertThat(encoder.matches(DEMO_PASSWORD, hash))
                    .as("seeded hash must match the documented demo password")
                    .isTrue();
        });

        assertThat(new HashSet<>(hashes)).as("distinct BCrypt salts").hasSize(5);
    }

    @Test
    void usernameUniquenessIsEnforcedByTheDatabase() {
        assertThatThrownBy(() -> jdbc.update(
                "INSERT INTO sys_user (username, password_hash, status, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                "admin", "$2a$10$duplicateProbe", "ACTIVE"))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void foreignKeysAreEnforcedByTheDatabase() {
        assertThatThrownBy(() -> jdbc.update(
                "INSERT INTO user_role (user_id, role_id) SELECT ?, id FROM sys_role WHERE role_code = 'ADMIN'",
                999_999L))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void roleCodeCheckConstraintRejectsAnUnknownRole() {
        assertThatThrownBy(() -> jdbc.update("INSERT INTO sys_role (role_code) VALUES ('SUPERUSER')"))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void subjectRejectsADataVersionThatIsNotADemoVersion() {
        assertThatThrownBy(() -> jdbc.update(
                "INSERT INTO subject (subject_code, alias, status, data_version, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                "DEMO-CHECK", "检查档案", "ACTIVE", "v1"))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void subjectAcceptsAValidDemoRowIncludingAChineseAlias() {
        int inserted = jdbc.update(
                "INSERT INTO subject (subject_code, alias, status, data_version, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                "DEMO-CHECK", "检查档案", "ACTIVE", "demo-v1");

        assertThat(inserted).isEqualTo(1);
        assertThat(jdbc.queryForObject(
                "SELECT alias FROM subject WHERE subject_code = ?", String.class, "DEMO-CHECK"))
                .isEqualTo("检查档案");
    }

    @Test
    void missingCognitiveScoresAreStoredAsNullAndNotAsZero() {
        jdbc.update(
                "INSERT INTO subject (subject_code, alias, status, data_version, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                "DEMO-MISSING", "缺失档案", "ACTIVE", "demo-v1");
        jdbc.update("""
                INSERT INTO visit (subject_id, visit_code, visit_date)
                SELECT id, ?, ? FROM subject WHERE subject_code = ?
                """, "BL", LocalDate.of(2025, 1, 1), "DEMO-MISSING");

        assertThat(jdbc.queryForObject("""
                SELECT v.mmse FROM visit v JOIN subject s ON s.id = v.subject_id WHERE s.subject_code = ?
                """, Double.class, "DEMO-MISSING")).isNull();
        assertThat(jdbc.queryForObject("""
                SELECT v.moca FROM visit v JOIN subject s ON s.id = v.subject_id WHERE s.subject_code = ?
                """, Double.class, "DEMO-MISSING")).isNull();
        assertThat(jdbc.queryForObject("""
                SELECT v.cdr_sb FROM visit v JOIN subject s ON s.id = v.subject_id WHERE s.subject_code = ?
                """, Double.class, "DEMO-MISSING")).isNull();
    }

    /** Every table in the application schema, excluding the engine's own schemas. */
    private List<String> applicationTables() throws SQLException {
        List<String> names = new ArrayList<>();
        try (Connection connection = dataSource.getConnection();
             ResultSet tables = connection.getMetaData()
                     .getTables(connection.getCatalog(), null, "%", new String[] { "TABLE" })) {
            while (tables.next()) {
                String schema = tables.getString("TABLE_SCHEM");
                if (schema != null && SYSTEM_SCHEMAS.contains(schema.toLowerCase(Locale.ROOT))) {
                    continue;
                }
                names.add(tables.getString("TABLE_NAME").toLowerCase(Locale.ROOT));
            }
        }
        return names;
    }
}
