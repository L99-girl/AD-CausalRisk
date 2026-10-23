package com.adcausalrisk.backend.config;

import java.time.Clock;
import java.time.ZoneId;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * The clock the business day is measured with.
 *
 * <p>Import validation rejects future dates, so "today" is a business decision, not a property of
 * the host. Reading {@code LocalDate.now()} directly would make the boundary follow whatever zone
 * the JVM happens to run in: a client east of the server would have its own "today" rejected as a
 * future date during the hours the two zones disagree. Pinning the zone makes the rule the same
 * everywhere and lets tests fix the clock.
 */
@Configuration
public class ClockConfig {

    /** The calendar zone the business day is defined in. */
    public static final ZoneId BUSINESS_ZONE = ZoneId.of("Asia/Shanghai");

    @Bean
    public Clock businessClock() {
        return Clock.system(BUSINESS_ZONE);
    }
}
