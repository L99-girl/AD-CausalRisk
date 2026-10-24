package com.adcausalrisk.backend.importjob.csv;

import java.util.ArrayList;
import java.util.List;

import com.adcausalrisk.backend.common.BusinessException;
import com.adcausalrisk.backend.common.ErrorCode;

/**
 * A small RFC 4180 reader, matching the behaviour the Python preflight relies on: comma
 * separated, {@code "} quoting, {@code ""} as an escaped quote, and quoted fields may contain
 * commas and line breaks.
 *
 * <p>Deliberate rules:
 *
 * <ul>
 *   <li>A single leading BOM is dropped; nothing else about the text is normalised, trimmed or
 *       repaired (the preflight rule is "no auto-trimming, no fixing values").</li>
 *   <li>Record line numbers are the physical line the record starts on.</li>
 *   <li>After a closing quote only {@code ,}, a line break or end of file is accepted - the
 *       strict-reader behaviour that rejects {@code "a"b} instead of silently concatenating.</li>
 *   <li>An unterminated quote is a format error for the whole file, because there is no way to
 *       recover record boundaries after it.</li>
 * </ul>
 */
public final class CsvParser {

    private CsvParser() {
        // utility class - no instances
    }

    public static List<CsvRecord> parse(String text) {
        String body = !text.isEmpty() && text.charAt(0) == '\uFEFF' ? text.substring(1) : text;

        List<CsvRecord> records = new ArrayList<>();
        List<String> fields = new ArrayList<>();
        StringBuilder field = new StringBuilder();
        boolean inQuotes = false;
        boolean started = false;
        int line = 1;
        int recordLine = 1;
        int index = 0;

        while (index < body.length()) {
            char current = body.charAt(index);

            if (inQuotes) {
                if (current == '"') {
                    if (index + 1 < body.length() && body.charAt(index + 1) == '"') {
                        field.append('"');
                        index += 2;
                        continue;
                    }
                    inQuotes = false;
                    index++;
                    if (index < body.length()) {
                        char next = body.charAt(index);
                        if (next != ',' && next != '\n' && next != '\r') {
                            throw formatError(line, "引号后出现意外字符");
                        }
                    }
                    continue;
                }
                if (current == '\n') {
                    line++;
                }
                field.append(current);
                index++;
                continue;
            }

            switch (current) {
                case '"' -> {
                    if (field.isEmpty()) {
                        inQuotes = true;
                        started = true;
                    } else {
                        // A quote inside an unquoted field is a literal character.
                        field.append(current);
                    }
                    index++;
                }
                case ',' -> {
                    fields.add(field.toString());
                    field.setLength(0);
                    started = true;
                    index++;
                }
                case '\r', '\n' -> {
                    if (current == '\r' && index + 1 < body.length() && body.charAt(index + 1) == '\n') {
                        index++;
                    }
                    fields.add(field.toString());
                    field.setLength(0);
                    records.add(new CsvRecord(recordLine, List.copyOf(fields)));
                    fields.clear();
                    started = false;
                    line++;
                    recordLine = line;
                    index++;
                }
                default -> {
                    field.append(current);
                    started = true;
                    index++;
                }
            }
        }

        if (inQuotes) {
            throw formatError(recordLine, "引号未闭合");
        }
        if (started || field.length() > 0 || !fields.isEmpty()) {
            fields.add(field.toString());
            records.add(new CsvRecord(recordLine, List.copyOf(fields)));
        }
        return records;
    }

    private static BusinessException formatError(int line, String detail) {
        return new BusinessException(ErrorCode.VALIDATION_ERROR, "CSV 第 " + line + " 行" + detail);
    }
}
