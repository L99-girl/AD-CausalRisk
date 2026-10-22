package com.adcausalrisk.backend.importjob.csv;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.LocalDate;
import java.util.Map;

import com.adcausalrisk.backend.common.BusinessException;

import org.junit.jupiter.api.Test;

/**
 * Pure unit tests for the CSV rules - no Spring context, no database.
 *
 * <p>The database answers the parser needs (does this subject exist, does this visit code already
 * exist) arrive through {@link ImportLookups}, so a small fake keeps every rule testable in
 * isolation.
 */
class CsvImportParserTest {

    private static final LocalDate TODAY = LocalDate.of(2026, 1, 1);

    private static final String SUBJECT_HEADER = "subjectCode,alias,status\n";

    private static final String VISIT_HEADER = "subjectCode,visitCode,visitDate,mmse,moca,cdrSb\n";

    private static final String FEATURE_HEADER = "subjectCode,featureName,featureValue,recordedAt,unit\n";

    private final CsvImportParser parser = new CsvImportParser();

    /** DEMO-001 and DEMO-002 exist; DEMO-001 already has a visit called BL. */
    private static ImportLookups lookups() {
        Map<String, Long> subjects = Map.of("DEMO-001", 1L, "DEMO-002", 2L);
        return new ImportLookups() {
            @Override
            public Long subjectIdOf(String subjectCode) {
                return subjects.get(subjectCode);
            }

            @Override
            public boolean visitExists(Long subjectId, String visitCode) {
                return Long.valueOf(1L).equals(subjectId) && "BL".equals(visitCode);
            }
        };
    }

    private ParsedImport parse(String csv) {
        return parser.parse(csv, lookups(), TODAY);
    }

    // ===================================================================
    // Header sniffing
    // ===================================================================

    @Test
    void exactHeaderSelectsTheTable() {
        assertThat(parse(SUBJECT_HEADER + "DEMO-001,甲,ACTIVE\n").table())
                .isEqualTo(ImportTable.SUBJECT);
        assertThat(parse(VISIT_HEADER + "DEMO-001,V1,2025-01-01,28,25,0.5\n").table())
                .isEqualTo(ImportTable.VISIT);
        assertThat(parse(FEATURE_HEADER + "DEMO-001,APOE_E4_COUNT,2,2025-01-01,count\n").table())
                .isEqualTo(ImportTable.FEATURE);
    }

    @Test
    void reorderedOrRenamedHeaderIsRefused() {
        assertThatThrownBy(() -> parse("alias,subjectCode,status\n甲,DEMO-001,ACTIVE\n"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("无法识别 CSV 表头");

        assertThatThrownBy(() -> parse("subjectCode,alias,state\nDEMO-001,甲,ACTIVE\n"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("无法识别 CSV 表头");
    }

    @Test
    void emptyFileIsRefused() {
        assertThatThrownBy(() -> parse(""))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("文件为空");
    }

    @Test
    void aSingleLeadingBomIsTolerated() {
        ParsedImport parsed = parse("\uFEFF" + SUBJECT_HEADER + "DEMO-100,甲,ACTIVE\n");

        assertThat(parsed.table()).isEqualTo(ImportTable.SUBJECT);
        assertThat(parsed.validRows()).isEqualTo(1);
    }

    // ===================================================================
    // CSV mechanics
    // ===================================================================

    @Test
    void quotedFieldsKeepCommasAndRowsReportPhysicalLines() {
        // The alias of record 3 contains a newline, so that record spans lines 3-4 and the next
        // record starts on line 5. The Python preflight reports that physical line, so must we.
        String csv = SUBJECT_HEADER
                + "DEMO-005,\"含,逗号\",ACTIVE\n"
                + "DEMO-006,\"两\n行\",ACTIVE\n"
                + "DEMO-007,x,BOGUS\n";

        ParsedImport parsed = parse(csv);

        assertThat(parsed.validRows()).isEqualTo(2);
        assertThat(parsed.invalidRows()).isEqualTo(1);
        assertThat(parsed.issues()).singleElement().satisfies(issue -> {
            assertThat(issue.rowNumber()).isEqualTo(5);
            assertThat(issue.field()).isEqualTo("status");
        });
    }

    @Test
    void escapedQuoteStaysInTheValue() {
        ParsedImport parsed = parse(SUBJECT_HEADER + "DEMO-101,\"a\"\"b\",ACTIVE\n");

        assertThat(parsed.validRows()).isEqualTo(1);
        assertThat(parsed.rows()).singleElement()
                .isInstanceOfSatisfying(ImportRow.Subject.class,
                        row -> assertThat(row.alias()).isEqualTo("a\"b"));
    }

    @Test
    void wrongColumnCountIsReportedAgainstTheRecord() {
        ParsedImport parsed = parse(SUBJECT_HEADER + "DEMO-001,甲\n");

        assertThat(parsed.validRows()).isZero();
        assertThat(parsed.issues()).singleElement().satisfies(issue -> {
            assertThat(issue.rowNumber()).isEqualTo(2);
            assertThat(issue.field()).isEmpty();
            assertThat(issue.message()).contains("列数为 2，应为 3");
        });
    }

    @Test
    void unterminatedQuoteFailsTheWholeFile() {
        assertThatThrownBy(() -> parse(SUBJECT_HEADER + "DEMO-001,\"甲,ACTIVE\n"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("引号未闭合");
    }

    // ===================================================================
    // Missing values and numbers
    // ===================================================================

    @Test
    void emptyScoreCellIsNullNeverZero() {
        ParsedImport parsed = parse(VISIT_HEADER + "DEMO-001,V1,2025-01-01,,,\n");

        assertThat(parsed.validRows()).isEqualTo(1);
        assertThat(parsed.rows()).singleElement()
                .isInstanceOfSatisfying(ImportRow.Visit.class, row -> {
                    assertThat(row.mmse()).isNull();
                    assertThat(row.moca()).isNull();
                    assertThat(row.cdrSb()).isNull();
                });
    }

    @Test
    void zeroIsPreservedAsZero() {
        ParsedImport parsed = parse(VISIT_HEADER + "DEMO-001,V1,2025-01-01,0,0,0\n");

        assertThat(parsed.rows()).singleElement()
                .isInstanceOfSatisfying(ImportRow.Visit.class, row -> {
                    assertThat(row.mmse()).isEqualByComparingTo("0");
                    assertThat(row.cdrSb()).isEqualByComparingTo("0");
                });
    }

    @Test
    void textThatOnlyLooksMissingIsRejected() {
        for (String literal : new String[] {"null", "NaN", "Infinity", "true", "false"}) {
            ParsedImport parsed = parse(VISIT_HEADER + "DEMO-001,V" + literal.length()
                    + ",2025-01-01," + literal + ",,\n");

            assertThat(parsed.validRows()).as("'%s' must not count as missing", literal).isZero();
            assertThat(parsed.issues()).as("'%s'", literal)
                    .anySatisfy(issue -> assertThat(issue.message()).contains("不是有效数值"));
        }
    }

    @Test
    void decimalScoresAreAccepted() {
        ParsedImport parsed = parse(VISIT_HEADER + "DEMO-001,V1,2025-01-01,28.5,25.25,1.75\n");

        assertThat(parsed.validRows()).isEqualTo(1);
        assertThat(parsed.rows()).singleElement()
                .isInstanceOfSatisfying(ImportRow.Visit.class,
                        row -> assertThat(row.mmse()).isEqualByComparingTo("28.5"));
    }

    @Test
    void scoresOutsideTheScaleRangeAreRejected() {
        assertThat(parse(VISIT_HEADER + "DEMO-001,V1,2025-01-01,30.5,,\n").issues())
                .anySatisfy(issue -> assertThat(issue.field()).isEqualTo("mmse"));
        assertThat(parse(VISIT_HEADER + "DEMO-001,V1,2025-01-01,,-1,\n").issues())
                .anySatisfy(issue -> assertThat(issue.field()).isEqualTo("moca"));
        assertThat(parse(VISIT_HEADER + "DEMO-001,V1,2025-01-01,,,18.1\n").issues())
                .anySatisfy(issue -> assertThat(issue.field()).isEqualTo("cdrSb"));
    }

    @Test
    void aScoreTooPreciseToStoreLosslesslyIsRejected() {
        String value = "1." + "1".repeat(62);

        assertThat(parse(VISIT_HEADER + "DEMO-001,V1,2025-01-01," + value + ",,\n").issues())
                .anySatisfy(issue -> assertThat(issue.message()).contains("小数位过多"));
    }

    // ===================================================================
    // Subject rules
    // ===================================================================

    @Test
    void subjectCodeAliasAndStatusAreValidated() {
        ParsedImport parsed = parse(SUBJECT_HEADER
                + "NOTDEMO,甲,ACTIVE\n"
                + "DEMO-002,," + "ACTIVE\n"
                + "DEMO-003,甲,DELETED\n");

        assertThat(parsed.validRows()).isZero();
        assertThat(parsed.issues()).extracting(RowIssue::field)
                .contains("subjectCode", "alias", "status");
    }

    @Test
    void subjectThatAlreadyExistsIsRejected() {
        ParsedImport parsed = parse(SUBJECT_HEADER + "DEMO-001,甲,ACTIVE\n");

        assertThat(parsed.validRows()).isZero();
        assertThat(parsed.issues()).singleElement()
                .satisfies(issue -> assertThat(issue.message()).contains("档案已存在"));
    }

    @Test
    void duplicateSubjectCodeWithinTheFileIsRejected() {
        ParsedImport parsed = parse(SUBJECT_HEADER
                + "DEMO-010,甲,ACTIVE\n"
                + "DEMO-010,乙,ACTIVE\n");

        assertThat(parsed.validRows()).isEqualTo(1);
        assertThat(parsed.issues()).singleElement()
                .satisfies(issue -> {
                    assertThat(issue.rowNumber()).isEqualTo(3);
                    assertThat(issue.message()).contains("文件内重复");
                });
    }

    // ===================================================================
    // Visit rules
    // ===================================================================

    @Test
    void visitForUnknownSubjectIsRejected() {
        assertThat(parse(VISIT_HEADER + "DEMO-999,V1,2025-01-01,28,25,0.5\n").issues())
                .singleElement()
                .satisfies(issue -> assertThat(issue.message()).contains("档案不存在"));
    }

    @Test
    void visitCodeThatAlreadyExistsForTheSubjectIsRejected() {
        assertThat(parse(VISIT_HEADER + "DEMO-001,BL,2025-01-01,28,25,0.5\n").issues())
                .singleElement()
                .satisfies(issue -> assertThat(issue.message()).contains("该档案下已存在"));
    }

    @Test
    void futureVisitDateIsRejected() {
        assertThat(parse(VISIT_HEADER + "DEMO-002,V1,2026-06-01,28,25,0.5\n").issues())
                .singleElement()
                .satisfies(issue -> assertThat(issue.message()).contains("未来日期"));
    }

    @Test
    void malformedDateIsRejected() {
        assertThat(parse(VISIT_HEADER + "DEMO-002,V1,2025/01/01,28,25,0.5\n").issues())
                .singleElement()
                .satisfies(issue -> assertThat(issue.message()).contains("不是有效日期"));
    }

    // ===================================================================
    // Feature rules
    // ===================================================================

    @Test
    void apoeMustBeWrittenAsALiteralInteger() {
        assertThat(parse(FEATURE_HEADER + "DEMO-001,APOE_E4_COUNT,2,2025-01-01,count\n")
                .validRows()).isEqualTo(1);

        for (String literal : new String[] {"1.0", "1e0", " 1", "3"}) {
            ParsedImport parsed =
                    parse(FEATURE_HEADER + "DEMO-001,APOE_E4_COUNT," + literal + ",2025-01-01,count\n");
            assertThat(parsed.validRows()).as("APOE '%s'", literal).isZero();
            assertThat(parsed.issues()).as("APOE '%s'", literal)
                    .anySatisfy(issue -> assertThat(issue.field()).isEqualTo("featureValue"));
        }
    }

    @Test
    void mriValueAndUnitMustMatchTheWhitelist() {
        assertThat(parse(FEATURE_HEADER + "DEMO-001,MRI_HIPPOCAMPUS_L,0.5,2025-01-01,normalized\n")
                .validRows()).isEqualTo(1);

        assertThat(parse(FEATURE_HEADER + "DEMO-001,MRI_HIPPOCAMPUS_L,1.5,2025-01-01,normalized\n")
                .issues()).anySatisfy(issue -> assertThat(issue.field()).isEqualTo("featureValue"));

        assertThat(parse(FEATURE_HEADER + "DEMO-001,MRI_HIPPOCAMPUS_L,0.5,2025-01-01,count\n")
                .issues()).anySatisfy(issue -> assertThat(issue.field()).isEqualTo("unit"));

        assertThat(parse(FEATURE_HEADER + "DEMO-001,APOE_E4_COUNT,1,2025-01-01,normalized\n")
                .issues()).anySatisfy(issue -> assertThat(issue.field()).isEqualTo("unit"));
    }

    @Test
    void unknownFeatureNameIsRejected() {
        assertThat(parse(FEATURE_HEADER + "DEMO-001,EEG_ALPHA,0.5,2025-01-01,normalized\n").issues())
                .anySatisfy(issue -> assertThat(issue.field()).isEqualTo("featureName"));
    }

    @Test
    void featureValueBeyondTheColumnScaleIsRejected() {
        assertThat(parse(FEATURE_HEADER + "DEMO-001,MRI_HIPPOCAMPUS_L,0.1234567,2025-01-01,normalized\n")
                .issues()).anySatisfy(issue -> assertThat(issue.message()).contains("小数位超过 6 位"));
    }

    // ===================================================================
    // Independent limits
    // ===================================================================

    @Test
    void byteLimitIsEnforcedBeforeParsing() {
        String oversized = SUBJECT_HEADER + "DEMO-001," + "a".repeat(CsvImportParser.MAX_BYTES)
                + ",ACTIVE\n";

        assertThatThrownBy(() -> parse(oversized))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("字节上限");
    }

    @Test
    void rowLimitIsEnforcedPerTable() {
        StringBuilder csv = new StringBuilder(SUBJECT_HEADER);
        for (int i = 1; i <= ImportTable.SUBJECT.maxRows() + 1; i++) {
            csv.append("DEMO-").append(String.format("%03d", i)).append(",甲,ACTIVE\n");
        }

        assertThatThrownBy(() -> parse(csv.toString()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("最多 " + ImportTable.SUBJECT.maxRows() + " 行");
    }

    @Test
    void countsAlwaysAddUp() {
        ParsedImport parsed = parse(SUBJECT_HEADER
                + "DEMO-020,甲,ACTIVE\n"
                + "DEMO-021,乙,ACTIVE\n"
                + "DEMO-021,丙,ACTIVE\n");

        assertThat(parsed.totalRows()).isEqualTo(3);
        assertThat(parsed.validRows()).isEqualTo(2);
        assertThat(parsed.invalidRows()).isEqualTo(1);
        assertThat(parsed.totalRows()).isEqualTo(parsed.validRows() + parsed.invalidRows());
    }

    @Test
    void headerWithoutDataRowsIsRefused() {
        // Ends with the header's own newline.
        assertThatThrownBy(() -> parse(SUBJECT_HEADER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("只有表头");

        // Ends without any newline at all.
        assertThatThrownBy(() -> parse("subjectCode,alias,status"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("只有表头");
    }

    @Test
    void aSubjectCannotReceiveMoreThanTheVisitCapInOneFile() {
        StringBuilder csv = new StringBuilder(VISIT_HEADER);
        int rows = CsvImportParser.MAX_VISITS_PER_SUBJECT + 1;
        for (int i = 1; i <= rows; i++) {
            csv.append("DEMO-002,V").append(i).append(",2025-01-01,28,25,0.5\n");
        }

        ParsedImport parsed = parse(csv.toString());

        assertThat(parsed.validRows()).isEqualTo(CsvImportParser.MAX_VISITS_PER_SUBJECT);
        assertThat(parsed.invalidRows()).isEqualTo(1);
        assertThat(parsed.issues()).singleElement().satisfies(issue -> {
            // The header is line 1, so the 101st data row starts on line 102.
            assertThat(issue.rowNumber()).isEqualTo(rows + 1);
            assertThat(issue.field()).isEqualTo("subjectCode");
            assertThat(issue.message()).contains("访视数超过上限");
        });
    }

    @Test
    void aSubjectCannotReceiveMoreThanTheFeatureCapInOneFile() {
        StringBuilder csv = new StringBuilder(FEATURE_HEADER);
        int rows = CsvImportParser.MAX_FEATURES_PER_SUBJECT + 1;
        for (int i = 1; i <= rows; i++) {
            csv.append("DEMO-002,APOE_E4_COUNT,1,2025-01-01,count\n");
        }

        ParsedImport parsed = parse(csv.toString());

        assertThat(parsed.validRows()).isEqualTo(CsvImportParser.MAX_FEATURES_PER_SUBJECT);
        assertThat(parsed.invalidRows()).isEqualTo(1);
        assertThat(parsed.issues()).singleElement().satisfies(issue -> {
            assertThat(issue.rowNumber()).isEqualTo(rows + 1);
            assertThat(issue.field()).isEqualTo("subjectCode");
            assertThat(issue.message()).contains("特征数超过上限");
        });
    }

    /**
     * The digest identifies the set of valid rows, not their order: reordering a file must not
     * force a re-preview, but swapping or editing a row must change the digest.
     */
    @Test
    void theDigestFollowsTheValidRowsNotTheirOrder() {
        ParsedImport first = parse(SUBJECT_HEADER + "DEMO-030,甲,ACTIVE\n" + "DEMO-031,乙,ACTIVE\n");
        ParsedImport reordered = parse(SUBJECT_HEADER + "DEMO-031,乙,ACTIVE\n"
                + "DEMO-030,甲,ACTIVE\n");
        ParsedImport editedAlias = parse(SUBJECT_HEADER + "DEMO-030,甲,ACTIVE\n"
                + "DEMO-031,丙,ACTIVE\n");
        ParsedImport oneRowFewer = parse(SUBJECT_HEADER + "DEMO-030,甲,ACTIVE\n");

        assertThat(first.digest()).describedAs("order must not matter").isEqualTo(reordered.digest());
        assertThat(first.digest()).describedAs("an edited row must change the digest")
                .isNotEqualTo(editedAlias.digest());
        assertThat(first.digest()).describedAs("a removed row must change the digest")
                .isNotEqualTo(oneRowFewer.digest());
        assertThat(first.digest()).hasSize(64);
    }
}
