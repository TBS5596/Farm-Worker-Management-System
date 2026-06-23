-- Create database
CREATE DATABASE IF NOT EXISTS farm_worker_db;
USE farm_worker_db;

-- Table: workers
CREATE TABLE workers (
    worker_id INT PRIMARY KEY AUTO_INCREMENT,
    full_name VARCHAR(100) NOT NULL,
    nrc_number VARCHAR(20) UNIQUE,
    phone_number VARCHAR(15),
    address TEXT,
    fingerprint_template BLOB,
    enrollment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status ENUM('active', 'inactive') DEFAULT 'active'
);

-- Table: attendance
CREATE TABLE attendance (
    attendance_id INT PRIMARY KEY AUTO_INCREMENT,
    worker_id INT NOT NULL,
    check_in_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    check_out_time TIMESTAMP NULL,
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    verified_by_cctv BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id) ON DELETE CASCADE
);

-- Table: cctv_feeds
CREATE TABLE cctv_feeds (
    feed_id INT PRIMARY KEY AUTO_INCREMENT,
    camera_name VARCHAR(50) NOT NULL,
    camera_location VARCHAR(100),
    rtsp_url VARCHAR(255),
    status ENUM('online', 'offline') DEFAULT 'offline',
    last_heartbeat TIMESTAMP NULL
);

-- Table: payroll
CREATE TABLE payroll (
    payroll_id INT PRIMARY KEY AUTO_INCREMENT,
    worker_id INT NOT NULL,
    week_ending DATE NOT NULL,
    total_hours DECIMAL(5,2),
    hourly_rate DECIMAL(10,2),
    gross_pay DECIMAL(10,2),
    napsa_deduction DECIMAL(10,2),
    nhima_deduction DECIMAL(10,2),
    net_pay DECIMAL(10,2),
    paid_status ENUM('pending', 'paid') DEFAULT 'pending',
    payment_date DATE,
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id) ON DELETE CASCADE
);

-- Table: users (for role-based access)
CREATE TABLE users (
    user_id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin', 'manager', 'supervisor', 'auditor') DEFAULT 'supervisor',
    worker_id INT NULL,
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id) ON DELETE SET NULL
);

-- Table: audit_logs
CREATE TABLE audit_logs (
    log_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT,
    action VARCHAR(100),
    details TEXT,
    ip_address VARCHAR(45),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
);

-- Insert sample data
INSERT INTO users (username, password_hash, role) VALUES 
('admin', '', 'admin');

INSERT INTO cctv_feeds (camera_name, camera_location, rtsp_url, status) VALUES
('Field_Cam_1', 'North Field', '', 'online'),
('Gate_Cam_1', 'Main Entrance', '', 'online');

-- Verify tables
SHOW TABLES;
SELECT * FROM users;

-- Biometric devices tracking (for hardware integration)
CREATE TABLE biometric_devices (
    device_id INT PRIMARY KEY AUTO_INCREMENT,
    device_name VARCHAR(50) NOT NULL,
    device_serial VARCHAR(100) UNIQUE,
    device_type ENUM('fingerprint', 'facial') DEFAULT 'fingerprint',
    ip_address VARCHAR(45),
    usb_port VARCHAR(20),
    status ENUM('active', 'inactive', 'offline') DEFAULT 'offline',
    last_heartbeat TIMESTAMP NULL,
    location VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Face templates (using facial recognition)
CREATE TABLE face_templates (
    face_id INT PRIMARY KEY AUTO_INCREMENT,
    worker_id INT NOT NULL,
    face_embedding BLOB NOT NULL,          
    reference_image_path VARCHAR(255),     -- path to stored reference image
    quality_score DECIMAL(5,2),            -- image quality score
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL,
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id) ON DELETE CASCADE
);

-- Biometric transaction logs (for debugging hardware and tracking events)
CREATE TABLE biometric_transactions (
    transaction_id INT PRIMARY KEY AUTO_INCREMENT,
    device_id INT,
    worker_id INT,
    transaction_type ENUM('enroll', 'verify', 'check_in', 'check_out') NOT NULL,
    success BOOLEAN DEFAULT FALSE,
    match_score DECIMAL(5,2),              -- fingerprint/face match confidence
    error_message TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id) REFERENCES biometric_devices(device_id),
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id)
);

-- CCTV recordings metadata (for recorded footage access from dashboard)
CREATE TABLE cctv_recordings (
    recording_id INT PRIMARY KEY AUTO_INCREMENT,
    camera_id INT,
    recording_path VARCHAR(255) NOT NULL,   -- file path or cloud URL
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NULL,
    file_size_bytes BIGINT,
    storage_location ENUM('local', 'cloud', 'both') DEFAULT 'local',
    cloud_url VARCHAR(500),                 -- for cloud storage access
    uploaded_to_cloud BOOLEAN DEFAULT FALSE,
    uploaded_at TIMESTAMP NULL,
    FOREIGN KEY (camera_id) REFERENCES cctv_feeds(feed_id) ON DELETE CASCADE
);

-- Event snapshots (photo or video clip captured at clock-in/out)
CREATE TABLE event_snapshots (
    snapshot_id INT PRIMARY KEY AUTO_INCREMENT,
    attendance_id INT NOT NULL,             -- links to attendance record
    camera_id INT,
    snapshot_type ENUM('photo', 'video_clip') DEFAULT 'photo',
    file_path VARCHAR(255) NOT NULL,
    cloud_url VARCHAR(500),
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (attendance_id) REFERENCES attendance(attendance_id) ON DELETE CASCADE,
    FOREIGN KEY (camera_id) REFERENCES cctv_feeds(feed_id) ON DELETE SET NULL
);

-- Offline sync queue (for handheld terminals in remote fields)
CREATE TABLE offline_sync_queue (
    sync_id INT PRIMARY KEY AUTO_INCREMENT,
    device_id INT,
    worker_id INT,
    operation_type ENUM('attendance_checkin', 'attendance_checkout', 'worker_enrollment', 'fingerprint_enrollment'),
    payload JSON NOT NULL,                  -- stores complete record as JSON
    sync_status ENUM('pending', 'synced', 'failed') DEFAULT 'pending',
    retry_count INT DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    synced_at TIMESTAMP NULL,
    FOREIGN KEY (device_id) REFERENCES biometric_devices(device_id)
);

-- Cloud sync metadata (track what has been uploaded to cloud)
CREATE TABLE cloud_sync_metadata (
    sync_id INT PRIMARY KEY AUTO_INCREMENT,
    table_name VARCHAR(50) NOT NULL,        -- e.g., 'attendance', 'workers', 'cctv_recordings'
    record_id INT NOT NULL,                 -- ID of record in local table
    cloud_status ENUM('pending', 'synced', 'failed') DEFAULT 'pending',
    cloud_record_id VARCHAR(100),           -- ID from cloud database
    last_sync_attempt TIMESTAMP NULL,
    synced_at TIMESTAMP NULL,
    UNIQUE KEY unique_record (table_name, record_id)
);



--  Add indexes for search functionality on existing tables
ALTER TABLE workers ADD INDEX idx_worker_name (full_name);
ALTER TABLE workers ADD INDEX idx_status (status);
ALTER TABLE workers ADD INDEX idx_enrollment_date (enrollment_date);

ALTER TABLE attendance ADD INDEX idx_check_in_time (check_in_time);
ALTER TABLE attendance ADD INDEX idx_worker_date (worker_id, check_in_time);

ALTER TABLE payroll ADD INDEX idx_week_ending (week_ending);
ALTER TABLE payroll ADD INDEX idx_paid_status (paid_status);

ALTER TABLE cctv_recordings ADD INDEX idx_recording_time (start_time);
ALTER TABLE cctv_recordings ADD INDEX idx_camera_time (camera_id, start_time);

-- Materialized view for daily attendance summary (for faster reporting)
CREATE TABLE daily_attendance_summary (
    summary_id INT PRIMARY KEY AUTO_INCREMENT,
    worker_id INT NOT NULL,
    summary_date DATE NOT NULL,
    check_in_time TIME,
    check_out_time TIME,
    total_hours DECIMAL(5,2),
    late_minutes INT DEFAULT 0,
    early_departure_minutes INT DEFAULT 0,
    verified_by_cctv BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id) ON DELETE CASCADE,
    UNIQUE KEY unique_worker_day (worker_id, summary_date)
);

-- Stored procedure to refresh daily summary (run at end of each day)
DELIMITER //
CREATE PROCEDURE refresh_daily_attendance_summary(IN target_date DATE)
BEGIN
    -- Clear existing summary for the date
    DELETE FROM daily_attendance_summary WHERE summary_date = target_date;
    
    -- Insert fresh summary
    INSERT INTO daily_attendance_summary (worker_id, summary_date, check_in_time, check_out_time, total_hours, verified_by_cctv)
    SELECT 
        a.worker_id,
        DATE(a.check_in_time) as summary_date,
        TIME(MIN(a.check_in_time)) as check_in_time,
        TIME(MAX(a.check_out_time)) as check_out_time,
        TIMESTAMPDIFF(HOUR, MIN(a.check_in_time), MAX(a.check_out_time)) as total_hours,
        MAX(a.verified_by_cctv) as verified_by_cctv
    FROM attendance a
    WHERE DATE(a.check_in_time) = target_date
    GROUP BY a.worker_id, DATE(a.check_in_time);
END //
DELIMITER ;


-- Hardware health logs (monitoring biometric scanners and cameras)
CREATE TABLE hardware_health_logs (
    log_id INT PRIMARY KEY AUTO_INCREMENT,
    device_type ENUM('biometric_scanner', 'cctv_camera') NOT NULL,
    device_id INT NOT NULL,
    status ENUM('online', 'offline', 'error', 'maintenance') DEFAULT 'offline',
    error_code VARCHAR(50),
    error_message TEXT,
    response_time_ms INT,                   -- device response time
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

SHOW TABLES;


