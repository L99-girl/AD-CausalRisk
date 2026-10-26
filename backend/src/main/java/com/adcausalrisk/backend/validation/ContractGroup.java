package com.adcausalrisk.backend.validation;

/**
 * Jakarta Validation group for constraints that <b>are part of the frozen
 * contract</b> and should be enforced for clients that rely on it (e.g. the
 * Python analytics side).
 *
 * <p>Controllers that support the QC-tolerant override mode (header
 * {@code X-Allow-OOR: true}) skip this group so callers can submit
 * out-of-clinical-range scores, which then flow into the QC engine instead
 * of being rejected with a 400. Controllers that do not opt into this mode
 * should validate with both {@link jakarta.validation.groups.Default} and
 * {@code ContractGroup} to preserve the Python-side contract verbatim.
 */
public interface ContractGroup {
}