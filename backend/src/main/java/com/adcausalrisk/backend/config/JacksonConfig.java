package com.adcausalrisk.backend.config;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.SerializationFeature;

import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Pins the JSON behaviour the frozen contract depends on, so it cannot drift silently
 * with a change somewhere else.
 *
 * <ol>
 *   <li><b>Nulls are always written.</b> {@code Envelope.data} is required by the contract
 *       and must appear as {@code null} when there is no payload. Boot's default already
 *       includes nulls; stating it here makes the guarantee explicit.
 *   <li><b>Unknown request properties are rejected.</b> Every request schema in
 *       {@code contracts/java-business.target.openapi.json} sets
 *       {@code additionalProperties: false}, so silently ignoring a misspelled or
 *       unauthorised field would accept a request the contract declares invalid. Boot
 *       disables this check by default, so it is enabled back. The rejection surfaces as
 *       {@code HttpMessageNotReadableException} &rarr; 400 {@code MALFORMED_JSON}.
 *   <li><b>Dates and times are ISO-8601 strings</b>, not epoch numbers, matching the
 *       contract's {@code format: date-time} / {@code format: date}.
 * </ol>
 */
@Configuration
public class JacksonConfig {

    @Bean
    Jackson2ObjectMapperBuilderCustomizer contractJsonCustomizer() {
        return builder -> builder
                .serializationInclusion(JsonInclude.Include.ALWAYS)
                .featuresToEnable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .featuresToDisable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    }
}
