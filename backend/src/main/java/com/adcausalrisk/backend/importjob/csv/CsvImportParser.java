package com.adcausalrisk.backend.importjob.csv;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

import org.springframework.stereotype.Component;

import com.adcausalrisk.backend.common.BusinessException;
import com.adcausalrisk.backend.common.ErrorCode;

/**
 * Validates one uploaded CSV and turns it into typed rows.
 *
 * <p><b>Scope.</b> Only rules that a single table can decide are enforced here. Cross-table
 * questions - "does this batch block on a 24-month window", "are there two visits on the index
 * day", "do same-day features conflict" - need all three tables at once and belong to the Python
 * preflight (<code>docs/Python_Csv_Preflight.md</code>); duplicating them here would produce a
 * second, divergent implementation.
 *
 * <p><b>Why a lookup callback instead of repositories.</b> Visit and feature rows refer to a
 * subject by code, and a visit code must be unique per subject, so validation needs two database
 * answers. They arrive through {@link ImportLookups} so this class stays pure and unit-testable.
 *
 * <p><b>Rules carried over from the Python preflight:</b>
 *
 * <ul>
 *   <li>Exact fixture headers identify the table; column names are never guessed or reordered.</li>
 *   <li>An empty cell means "not recorded" and stays {@code null} - it is never turned into 0.
 *       This holds for visit scores <i>and</i> for {@code featureValue}.</li>
 *   <li>{@code null}/{@code NaN}/{@code Infinity}/{@code true}/{@code false} written as text are
 *       <i>not</i> missing values; they are invalid numbers.</li>
 *   <li>Every date must be a real past-or-present date: a future date and a year of 0 or less are
 *       both rejected, for {@code visitDate} and {@code recordedAt} alike.</li>
 *   <li>Values are not trimmed, rounded or repaired. {@code 0} stays {@code 0}, decimals stay
 *       decimals, and a value that cannot be stored without loss is rejected.</li>
 *   <li>APOE_E4_COUNT must be written as {@code 0}, {@code 1} or {@code 2}; {@code 1.0} and
 *       {@code 1e0} are rejected rather than silently coerced.</li>
 *   <li>Bytes and row counts are separate, independent limits.</li>
 * </ul>
 *
 * <p>Issue messages never echo a cell's text, so a rejected value cannot leak through the error
 * report - the same reason the Python preflight only returns stable codes.
 */
@Component
public class CsvImportParser {

    /** The three tables together may not exceed this many UTF-8 bytes. */
    public static final int MAX_BYTES = 30_000;

    /** How many issues the response may carry; the counts stay exact beyond it. */
    public static final int MAX_ISSUES = 200;

    private static final Set<String> NOT_A_NUMBER =
            Set.of("null", "nan", "infinity", "-infinity", "inf", "-inf", "true", "false");

    private static final Set<String> FEATURE_NAMES =
            Set.of("APOE_E4_COUNT", "MRI_HIPPOCAMPUS_L", "MRI_HIPPOCAMPUS_R");

    private static final Set<String> APOE_LITERALS = Set.of("0", "1", "2");

    /** Zero-width code points that render as nothing; text made only of them reads as empty. */
    private static final Set<Integer> INVISIBLE_CODE_POINTS =
            Set.of(0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF);

    private static final BigDecimal MMSE_MAX = new BigDecimal("30");

    private static final BigDecimal CDR_SB_MAX = new BigDecimal("18");

    private static final int VISIT_RAW_LITERAL_LIMIT = 64;

    private static final int VISIT_RAW_SCALE_LIMIT = 61;

    /** {@code subject_feature.feature_value} is DECIMAL(18,6). */
    private static final int FEATURE_SCALE_LIMIT = 6;

    private static final int ALIAS_MAX = 100;

    private static final int VISIT_CODE_MAX = 50;

    private static final String SUBJECT_CODE_PATTERN = "^DEMO-[A-Za-z0-9-]{1,45}$";

    /** The Python preflight caps per subject, on top of the per-table row limits. */
    public static final int MAX_VISITS_PER_SUBJECT = 100;

    public static final int MAX_FEATURES_PER_SUBJECT = 500;

    public ParsedImport parse(String text, ImportLookups lookups, LocalDate today) {
        if (text.getBytes(StandardCharsets.UTF_8).length > MAX_BYTES) {
            throw fail("文件超过 " + MAX_BYTES + " 字节上限");
        }

        List<CsvRecord> records = CsvParser.parse(text);
        if (records.isEmpty()) {
            throw fail("文件为空");
        }

        ImportTable table = sniff(records.get(0));
        List<CsvRecord> dataRecords =
                records.size() > 1 ? records.subList(1, records.size()) : List.<CsvRecord>of();
        // A header with no rows is a mistake, not a valid empty batch: there is nothing to
        // preview and nothing to commit, and accepting it would leave an unusable BLOCKED job.
        if (dataRecords.isEmpty()) {
            throw fail("文件只有表头，没有数据行");
        }
        if (dataRecords.size() > table.maxRows()) {
            throw fail(table.displayName() + " 最多 " + table.maxRows() + " 行，实际 "
                    + dataRecords.size() + " 行");
        }

        List<ImportRow> rows = new ArrayList<>();
        List<RowIssue> issues = new ArrayList<>();
        switch (table) {
            case SUBJECT -> parseSubjects(dataRecords, lookups, rows, issues);
            case VISIT -> parseVisits(dataRecords, lookups, today, rows, issues);
            case FEATURE -> parseFeatures(dataRecords, lookups, today, rows, issues);
        }
        rows = capPerSubject(table, rows, issues);
        return new ParsedImport(table, dataRecords.size(), rows.size(),
                dataRecords.size() - rows.size(), List.copyOf(issues), List.copyOf(rows));
    }

    /**
     * Enforces the preflight's per-subject ceilings (100 visits, 500 features) on top of the
     * per-table row limit. Rows past the ceiling become row-level issues rather than failing the
     * whole upload, so one over-full subject does not reject the rest of the file.
     */
    private static List<ImportRow> capPerSubject(ImportTable table, List<ImportRow> rows,
                                                 List<RowIssue> issues) {
        int limit = switch (table) {
            case VISIT -> MAX_VISITS_PER_SUBJECT;
            case FEATURE -> MAX_FEATURES_PER_SUBJECT;
            case SUBJECT -> 0;
        };
        if (limit == 0) {
            return rows;
        }
        String label = table == ImportTable.VISIT ? "访视" : "特征";
        Map<Long, Integer> counts = new HashMap<>();
        List<ImportRow> kept = new ArrayList<>(rows.size());
        for (ImportRow row : rows) {
            Long subjectId = switch (row) {
                case ImportRow.Visit visit -> visit.subjectId();
                case ImportRow.Feature feature -> feature.subjectId();
                case ImportRow.Subject subject -> null;
            };
            int count = counts.merge(subjectId, 1, Integer::sum);
            if (count > limit) {
                issues.add(new RowIssue(row.rowNumber(), "subjectCode",
                        "该档案" + label + "数超过上限 " + limit));
            } else {
                kept.add(row);
            }
        }
        return kept;
    }

    /** The table whose exact header matches this header row. */
    public ImportTable sniff(CsvRecord header) {
        for (ImportTable table : ImportTable.values()) {
            if (table.header().equals(header.fields())) {
                return table;
            }
        }
        throw fail("无法识别 CSV 表头，应为 subjects/visits/features 之一的原始表头（字段名与顺序必须一致）");
    }

    // ===================================================================
    // Per-table validation
    // ===================================================================

    private void parseSubjects(List<CsvRecord> records, ImportLookups lookups,
                               List<ImportRow> rows, List<RowIssue> issues) {
        Set<String> seen = new HashSet<>();
        for (CsvRecord record : records) {
            if (wrongColumnCount(record, ImportTable.SUBJECT, issues)) {
                continue;
            }
            int row = record.lineNumber();
            int before = issues.size();

            String subjectCode = record.field(0);
            String alias = record.field(1);
            String status = record.field(2);

            if (subjectCode.isEmpty()) {
                issue(issues, row, "subjectCode", "不能为空");
            } else if (!subjectCode.matches(SUBJECT_CODE_PATTERN)) {
                issue(issues, row, "subjectCode", "格式无效，须匹配 DEMO-[A-Za-z0-9-]{1,45}");
            }

            if (isBlankOrInvisible(alias)) {
                issue(issues, row, "alias", "不能为空");
            } else if (alias.length() > ALIAS_MAX) {
                issue(issues, row, "alias", "长度不能超过 " + ALIAS_MAX);
            }

            if (!"ACTIVE".equals(status) && !"ARCHIVED".equals(status)) {
                issue(issues, row, "status", "只能是 ACTIVE 或 ARCHIVED");
            }

            if (issues.size() == before && !seen.add(subjectCode)) {
                issue(issues, row, "subjectCode", "文件内重复");
            }
            if (issues.size() == before && lookups.subjectIdOf(subjectCode) != null) {
                issue(issues, row, "subjectCode", "档案已存在");
            }
            if (issues.size() == before) {
                rows.add(new ImportRow.Subject(row, subjectCode, alias, status));
            }
        }
    }

    private void parseVisits(List<CsvRecord> records, ImportLookups lookups, LocalDate today,
                             List<ImportRow> rows, List<RowIssue> issues) {
        Set<String> seen = new HashSet<>();
        for (CsvRecord record : records) {
            if (wrongColumnCount(record, ImportTable.VISIT, issues)) {
                continue;
            }
            int row = record.lineNumber();
            int before = issues.size();

            String subjectCode = record.field(0);
            Long subjectId = subjectCode.isEmpty() ? null : lookups.subjectIdOf(subjectCode);
            if (subjectCode.isEmpty()) {
                issue(issues, row, "subjectCode", "不能为空");
            } else if (subjectId == null) {
                issue(issues, row, "subjectCode", "档案不存在");
            }

            String visitCode = record.field(1);
            if (visitCode.isEmpty()) {
                issue(issues, row, "visitCode", "不能为空");
            } else if (visitCode.length() > VISIT_CODE_MAX) {
                issue(issues, row, "visitCode", "长度不能超过 " + VISIT_CODE_MAX);
            }

            LocalDate visitDate = date(record.field(2), row, "visitDate", today, issues);
            BigDecimal mmse = score(record.field(3), row, "mmse", MMSE_MAX, issues);
            BigDecimal moca = score(record.field(4), row, "moca", MMSE_MAX, issues);
            BigDecimal cdrSb = score(record.field(5), row, "cdrSb", CDR_SB_MAX, issues);

            if (issues.size() == before && subjectId != null
                    && !seen.add(subjectId + "|" + visitCode)) {
                issue(issues, row, "visitCode", "文件内同一档案下重复");
            }
            if (issues.size() == before && lookups.visitExists(subjectId, visitCode)) {
                issue(issues, row, "visitCode", "该档案下已存在");
            }
            if (issues.size() == before) {
                rows.add(new ImportRow.Visit(row, subjectId, visitCode, visitDate,
                        mmse, moca, cdrSb));
            }
        }
    }

    private void parseFeatures(List<CsvRecord> records, ImportLookups lookups, LocalDate today,
                               List<ImportRow> rows, List<RowIssue> issues) {
        for (CsvRecord record : records) {
            if (wrongColumnCount(record, ImportTable.FEATURE, issues)) {
                continue;
            }
            int row = record.lineNumber();
            int before = issues.size();

            String subjectCode = record.field(0);
            Long subjectId = subjectCode.isEmpty() ? null : lookups.subjectIdOf(subjectCode);
            if (subjectCode.isEmpty()) {
                issue(issues, row, "subjectCode", "不能为空");
            } else if (subjectId == null) {
                issue(issues, row, "subjectCode", "档案不存在");
            }

            String featureName = record.field(1);
            String unit = record.field(4);
            boolean knownFeature = FEATURE_NAMES.contains(featureName);
            if (!knownFeature) {
                issue(issues, row, "featureName",
                        "必须是 APOE_E4_COUNT、MRI_HIPPOCAMPUS_L 或 MRI_HIPPOCAMPUS_R");
            }

            BigDecimal featureValue = featureValue(record.field(2), row, featureName, issues);

            if (knownFeature) {
                String expectedUnit = "APOE_E4_COUNT".equals(featureName) ? "count" : "normalized";
                if (!expectedUnit.equals(unit)) {
                    issue(issues, row, "unit", "该特征的单位必须是 " + expectedUnit);
                }
            }

            LocalDate recordedAt = date(record.field(3), row, "recordedAt", today, issues);

            if (issues.size() == before) {
                rows.add(new ImportRow.Feature(row, subjectId, featureName, featureValue,
                        recordedAt, unit));
            }
        }
    }

    private static BigDecimal featureValue(String text, int row, String featureName,
                                           List<RowIssue> issues) {
        // An empty cell is a missing observation, exactly as it is for a visit score: it stays
        // null and is never an error. subject_feature.feature_value is nullable for this reason.
        // Only text that merely *looks* missing ("null", "NaN", ...) is rejected below.
        if (text.isEmpty()) {
            return null;
        }
        if ("APOE_E4_COUNT".equals(featureName)) {
            if (!APOE_LITERALS.contains(text)) {
                issue(issues, row, "featureValue", "APOE_E4_COUNT 必须写整数 0、1 或 2");
                return null;
            }
            return new BigDecimal(text);
        }
        if (!featureName.startsWith("MRI_")) {
            return null;
        }
        BigDecimal value = number(text, row, "featureValue", issues);
        if (value == null) {
            return null;
        }
        if (value.signum() < 0 || value.compareTo(BigDecimal.ONE) > 0) {
            issue(issues, row, "featureValue", "必须在 0 到 1 之间");
            return null;
        }
        if (value.scale() > FEATURE_SCALE_LIMIT) {
            issue(issues, row, "featureValue", "小数位超过 " + FEATURE_SCALE_LIMIT + " 位，无法无损保存");
            return null;
        }
        return value;
    }

    // ===================================================================
    // Field helpers
    // ===================================================================

    /**
     * True when a value would look empty to a reader: nothing but whitespace or zero-width
     * characters. {@link String#isBlank()} on its own lets a value made of U+200B through, which
     * renders as an empty alias.
     */
    private static boolean isBlankOrInvisible(String text) {
        return text.codePoints()
                .allMatch(codePoint -> Character.isWhitespace(codePoint)
                        || INVISIBLE_CODE_POINTS.contains(codePoint));
    }

    private static boolean wrongColumnCount(CsvRecord record, ImportTable table,
                                            List<RowIssue> issues) {
        if (record.fields().size() == table.header().size()) {
            return false;
        }
        issue(issues, record.lineNumber(), "",
                "列数为 " + record.fields().size() + "，应为 " + table.header().size());
        return true;
    }

    /**
     * A date cell. Both rules apply to <i>every</i> date field: a future date is not a recorded
     * observation, and year 0 (or earlier) is not a real calendar date in this domain even though
     * ISO-8601 lets {@link LocalDate} represent it.
     */
    private static LocalDate date(String text, int row, String field, LocalDate today,
                                  List<RowIssue> issues) {
        if (text.isEmpty()) {
            issue(issues, row, field, "不能为空");
            return null;
        }
        LocalDate parsed;
        try {
            parsed = LocalDate.parse(text);
        } catch (DateTimeParseException exception) {
            issue(issues, row, field, "不是有效日期，应为 yyyy-MM-dd");
            return null;
        }
        if (parsed.getYear() <= 0) {
            issue(issues, row, field, "年份必须大于 0");
            return null;
        }
        if (parsed.isAfter(today)) {
            issue(issues, row, field, "不能是未来日期");
            return null;
        }
        return parsed;
    }

    /**
     * A cognitive score. An empty cell is a missing observation and stays {@code null} - it is
     * never reported as 0.
     */
    private static BigDecimal score(String text, int row, String field, BigDecimal max,
                                    List<RowIssue> issues) {
        if (text.isEmpty()) {
            return null;
        }
        BigDecimal value = number(text, row, field, issues);
        if (value == null) {
            return null;
        }
        if (value.signum() < 0 || value.compareTo(max) > 0) {
            issue(issues, row, field, "必须在 0 到 " + max.toPlainString() + " 之间");
            return null;
        }
        if (value.scale() > VISIT_RAW_SCALE_LIMIT
                || value.toString().length() > VISIT_RAW_LITERAL_LIMIT) {
            issue(issues, row, field, "小数位过多，无法无损保存");
            return null;
        }
        return value;
    }

    /** A decimal cell, rejecting the text literals that only look like missing values. */
    private static BigDecimal number(String text, int row, String field, List<RowIssue> issues) {
        if (NOT_A_NUMBER.contains(text.toLowerCase(Locale.ROOT))) {
            issue(issues, row, field, "不是有效数值");
            return null;
        }
        try {
            return new BigDecimal(text);
        } catch (NumberFormatException exception) {
            issue(issues, row, field, "不是有效数值");
            return null;
        }
    }

    private static void issue(List<RowIssue> issues, int row, String field, String message) {
        issues.add(new RowIssue(row, field, message));
    }

    private static BusinessException fail(String message) {
        return new BusinessException(ErrorCode.VALIDATION_ERROR, message);
    }
}
