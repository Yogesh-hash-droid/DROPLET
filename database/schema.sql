-- Smart Water Quality Monitoring Database Schema
CREATE DATABASE IF NOT EXISTS water_quality_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE water_quality_db;

-- 1. Devices Table
CREATE TABLE IF NOT EXISTS devices (
    id INT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL UNIQUE,
    device_name VARCHAR(128) NOT NULL,
    source ENUM('SIMULATION', 'ESP32') NOT NULL DEFAULT 'SIMULATION',
    status ENUM('ONLINE', 'OFFLINE') NOT NULL DEFAULT 'OFFLINE',
    last_seen TIMESTAMP NULL DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_device_id (device_id),
    INDEX idx_last_seen (last_seen)
) ENGINE=InnoDB;

-- 2. Water Readings Table
CREATE TABLE IF NOT EXISTS water_readings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL,
    ph FLOAT NOT NULL,
    tds FLOAT NOT NULL,
    turbidity FLOAT NOT NULL,
    temperature FLOAT NOT NULL,
    source ENUM('SIMULATION', 'ESP32') NOT NULL DEFAULT 'SIMULATION',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_timestamp (timestamp),
    INDEX idx_source (source),
    INDEX idx_device_reading (device_id, timestamp),
    CONSTRAINT fk_readings_device FOREIGN KEY (device_id) 
        REFERENCES devices(device_id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

-- 3. Predictions Table
CREATE TABLE IF NOT EXISTS predictions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    reading_id INT NOT NULL,
    prediction ENUM('POTABLE', 'NOT POTABLE') NULL DEFAULT NULL,
    confidence FLOAT NULL DEFAULT NULL,
    quality_score FLOAT NOT NULL,
    safety_status ENUM('SAFE', 'WARNING', 'UNSAFE') NOT NULL,
    warning_message TEXT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_pred_timestamp (timestamp),
    INDEX idx_safety (safety_status),
    INDEX idx_prediction (prediction),
    CONSTRAINT fk_prediction_reading FOREIGN KEY (reading_id) 
        REFERENCES water_readings(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 4. System Config Table
CREATE TABLE IF NOT EXISTS system_config (
    id INT PRIMARY KEY DEFAULT 1,
    ph_min FLOAT NOT NULL DEFAULT 6.5,
    ph_max FLOAT NOT NULL DEFAULT 8.5,
    tds_max FLOAT NOT NULL DEFAULT 500.0,
    turbidity_max FLOAT NOT NULL DEFAULT 5.0,
    temperature_min FLOAT NOT NULL DEFAULT 10.0,
    temperature_max FLOAT NOT NULL DEFAULT 35.0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT single_row CHECK (id = 1)
) ENGINE=InnoDB;

-- Seed Default Thresholds
INSERT INTO system_config (id, ph_min, ph_max, tds_max, turbidity_max, temperature_min, temperature_max)
VALUES (1, 6.5, 8.5, 500.0, 5.0, 10.0, 35.0)
ON DUPLICATE KEY UPDATE id=1;

-- Seed default simulator device
INSERT INTO devices (device_id, device_name, source, status, last_seen)
VALUES ('SIMULATOR-001', 'Software Telemetry Simulator', 'SIMULATION', 'ONLINE', CURRENT_TIMESTAMP)
ON DUPLICATE KEY UPDATE device_name=VALUES(device_name);
