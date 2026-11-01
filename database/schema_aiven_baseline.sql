-- DROPLET Aiven MySQL baseline schema
-- Target: a new, empty Aiven MySQL database (for example, `defaultdb`).
-- This file is schema-only: it does not create a database, connect to Aiven,
-- modify an existing database, or execute the Phase 10 ALTER migration.
--
-- Source of truth: backend/app/models/*.py
-- The application provisions the system_config row when first accessed.
-- No simulator or historical data is inserted here.

USE defaultdb;

CREATE TABLE devices (
    id INT NOT NULL AUTO_INCREMENT,
    device_id VARCHAR(64) NOT NULL,
    device_name VARCHAR(128) NOT NULL,
    source ENUM('SIMULATION', 'ESP32', 'ESP8266') NOT NULL,
    status ENUM('ONLINE', 'OFFLINE') NOT NULL,
    last_seen DATETIME NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    UNIQUE INDEX ix_devices_device_id (device_id),
    INDEX ix_devices_id (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE system_config (
    id INT NOT NULL,
    ph_min FLOAT NULL COMMENT 'legacy column; NULL = not configured',
    ph_max FLOAT NULL COMMENT 'legacy column; NULL = not configured',
    tds_max FLOAT NOT NULL,
    turbidity_max FLOAT NOT NULL,
    temperature_min FLOAT NULL COMMENT 'legacy column; NULL = not configured',
    temperature_max FLOAT NULL COMMENT 'legacy column; NULL = not configured',
    status_good_min FLOAT NOT NULL DEFAULT 70.0,
    status_poor_max FLOAT NOT NULL DEFAULT 40.0,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE water_readings (
    id INT NOT NULL AUTO_INCREMENT,
    device_id VARCHAR(64) NOT NULL,
    ph FLOAT NULL COMMENT 'legacy column; NULL = not measured',
    tds FLOAT NOT NULL,
    turbidity FLOAT NOT NULL,
    temperature FLOAT NULL COMMENT 'legacy column; NULL = not measured',
    source ENUM('SIMULATION', 'ESP32', 'ESP8266') NOT NULL,
    timestamp DATETIME NOT NULL,
    PRIMARY KEY (id),
    INDEX ix_water_readings_id (id),
    INDEX ix_water_readings_device_id (device_id),
    INDEX ix_water_readings_timestamp (timestamp),
    INDEX ix_water_readings_source (source),
    CONSTRAINT fk_water_readings_device
        FOREIGN KEY (device_id) REFERENCES devices (device_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE predictions (
    id INT NOT NULL AUTO_INCREMENT,
    reading_id INT NOT NULL,
    prediction ENUM('POTABLE', 'NOT POTABLE') NULL,
    confidence FLOAT NULL,
    quality_score FLOAT NOT NULL,
    score_method ENUM('FOUR_PARAM_LEGACY', 'TWO_PARAM_SCREENING') NULL,
    safety_status ENUM('SAFE', 'WARNING', 'UNSAFE') NOT NULL,
    warning_message TEXT NULL,
    timestamp DATETIME NOT NULL,
    PRIMARY KEY (id),
    UNIQUE INDEX ix_predictions_reading_id (reading_id),
    INDEX ix_predictions_timestamp (timestamp),
    INDEX ix_predictions_safety_status (safety_status),
    INDEX ix_predictions_score_method (score_method),
    INDEX ix_predictions_id (id),
    INDEX ix_predictions_prediction (prediction),
    CONSTRAINT fk_predictions_reading
        FOREIGN KEY (reading_id) REFERENCES water_readings (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
