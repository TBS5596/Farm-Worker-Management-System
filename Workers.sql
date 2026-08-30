-- ---------------------------------------------------------------------------
-- Farm Worker Management System - database schema
--
-- GENERATED FILE. Do not edit by hand.
-- Source of truth: models.py
-- Regenerate with: python tools/export_schema.py
-- Generated: 2026-08-28 10:02:43 UTC
-- Dialect: SQLite (the deployment target; Postgres or MySQL need type tweaks)
-- ---------------------------------------------------------------------------

-- Table: biometric_devices
CREATE TABLE biometric_devices (
	device_id INTEGER NOT NULL, 
	device_name VARCHAR(50) NOT NULL, 
	device_serial VARCHAR(100), 
	device_type VARCHAR(20) NOT NULL, 
	ip_address VARCHAR(45), 
	usb_port VARCHAR(20), 
	status VARCHAR(20) NOT NULL, 
	last_heartbeat DATETIME, 
	location VARCHAR(100), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (device_id), 
	UNIQUE (device_serial)
);

-- Table: cctv_feeds
CREATE TABLE cctv_feeds (
	feed_id INTEGER NOT NULL, 
	camera_name VARCHAR(50) NOT NULL, 
	camera_location VARCHAR(100), 
	rtsp_url VARCHAR(255), 
	status VARCHAR(20) NOT NULL, 
	is_primary BOOLEAN NOT NULL, 
	last_heartbeat DATETIME, 
	PRIMARY KEY (feed_id)
);

-- Table: cloud_sync_metadata
CREATE TABLE cloud_sync_metadata (
	sync_id INTEGER NOT NULL, 
	table_name VARCHAR(50) NOT NULL, 
	record_id INTEGER NOT NULL, 
	cloud_status VARCHAR(20) NOT NULL, 
	cloud_record_id VARCHAR(100), 
	last_sync_attempt DATETIME, 
	synced_at DATETIME, 
	PRIMARY KEY (sync_id), 
	CONSTRAINT uq_cloud_sync_table_record UNIQUE (table_name, record_id)
);

-- Table: hardware_health_logs
CREATE TABLE hardware_health_logs (
	log_id INTEGER NOT NULL, 
	device_type VARCHAR(30) NOT NULL, 
	device_id INTEGER NOT NULL, 
	device_label VARCHAR(120), 
	status VARCHAR(20) NOT NULL, 
	error_code VARCHAR(50), 
	error_message TEXT, 
	response_time_ms INTEGER, 
	logged_at DATETIME NOT NULL, 
	PRIMARY KEY (log_id)
);

-- Table: settings
CREATE TABLE settings (
	id INTEGER NOT NULL, 
	"key" VARCHAR(100) NOT NULL, 
	value TEXT, 
	PRIMARY KEY (id), 
	UNIQUE ("key")
);

-- Table: workers
CREATE TABLE workers (
	id INTEGER NOT NULL, 
	worker_id VARCHAR(20) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	nrc_number VARCHAR(20), 
	pin_hash VARCHAR(256) NOT NULL, 
	pin_fingerprint VARCHAR(64), 
	fingerprint_template BLOB, 
	phone_number VARCHAR(30), 
	address VARCHAR(255), 
	emergency_contact VARCHAR(120), 
	department VARCHAR(80), 
	hourly_rate FLOAT, 
	face_enrolled_at DATETIME, 
	enrollment_date DATETIME, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (worker_id), 
	UNIQUE (nrc_number)
);

-- Table: attendance
CREATE TABLE attendance (
	attendance_id INTEGER NOT NULL, 
	worker_id INTEGER NOT NULL, 
	check_in_time DATETIME NOT NULL, 
	check_out_time DATETIME, 
	latitude FLOAT, 
	longitude FLOAT, 
	verified_by_cctv BOOLEAN NOT NULL, 
	verified_by_face BOOLEAN NOT NULL, 
	check_in_match_score FLOAT, 
	check_out_match_score FLOAT, 
	within_geofence BOOLEAN, 
	distance_from_farm_m FLOAT, 
	PRIMARY KEY (attendance_id), 
	FOREIGN KEY(worker_id) REFERENCES workers (id)
);

-- Table: biometric_transactions
CREATE TABLE biometric_transactions (
	transaction_id INTEGER NOT NULL, 
	device_id INTEGER, 
	worker_id INTEGER, 
	transaction_type VARCHAR(30) NOT NULL, 
	modality VARCHAR(20) NOT NULL, 
	success BOOLEAN NOT NULL, 
	match_score FLOAT, 
	threshold_used FLOAT, 
	error_message TEXT, 
	timestamp DATETIME NOT NULL, 
	PRIMARY KEY (transaction_id), 
	FOREIGN KEY(device_id) REFERENCES biometric_devices (device_id), 
	FOREIGN KEY(worker_id) REFERENCES workers (id)
);

-- Table: daily_attendance_summary
CREATE TABLE daily_attendance_summary (
	summary_id INTEGER NOT NULL, 
	worker_id INTEGER NOT NULL, 
	summary_date DATE NOT NULL, 
	check_in_time TIME, 
	check_out_time TIME, 
	total_hours FLOAT, 
	overtime_hours FLOAT NOT NULL, 
	sessions_count INTEGER NOT NULL, 
	late_minutes INTEGER NOT NULL, 
	early_departure_minutes INTEGER NOT NULL, 
	verified_by_cctv BOOLEAN NOT NULL, 
	verified_by_face BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (summary_id), 
	CONSTRAINT uq_daily_attendance_worker_day UNIQUE (worker_id, summary_date), 
	FOREIGN KEY(worker_id) REFERENCES workers (id)
);

-- Table: face_templates
CREATE TABLE face_templates (
	face_id INTEGER NOT NULL, 
	worker_id INTEGER NOT NULL, 
	face_embedding BLOB NOT NULL, 
	algorithm VARCHAR(30) NOT NULL, 
	sample_index INTEGER NOT NULL, 
	reference_image_path VARCHAR(255), 
	quality_score FLOAT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME, 
	PRIMARY KEY (face_id), 
	FOREIGN KEY(worker_id) REFERENCES workers (id)
);

-- Table: offline_sync_queue
CREATE TABLE offline_sync_queue (
	sync_id INTEGER NOT NULL, 
	device_id INTEGER, 
	worker_id INTEGER, 
	operation_type VARCHAR(50) NOT NULL, 
	payload TEXT NOT NULL, 
	sync_status VARCHAR(20) NOT NULL, 
	retry_count INTEGER NOT NULL, 
	last_error TEXT, 
	created_at DATETIME NOT NULL, 
	synced_at DATETIME, 
	PRIMARY KEY (sync_id), 
	FOREIGN KEY(device_id) REFERENCES biometric_devices (device_id), 
	FOREIGN KEY(worker_id) REFERENCES workers (id)
);

-- Table: payroll
CREATE TABLE payroll (
	payroll_id INTEGER NOT NULL, 
	worker_id INTEGER NOT NULL, 
	week_ending DATE NOT NULL, 
	total_hours FLOAT, 
	overtime_hours FLOAT, 
	hourly_rate FLOAT, 
	overtime_pay FLOAT, 
	gross_pay FLOAT, 
	napsa_rate FLOAT, 
	nhima_rate FLOAT, 
	napsa_deduction FLOAT, 
	nhima_deduction FLOAT, 
	net_pay FLOAT, 
	computed_from_attendance BOOLEAN NOT NULL, 
	generated_at DATETIME, 
	paid_status VARCHAR(20) NOT NULL, 
	payment_date DATE, 
	PRIMARY KEY (payroll_id), 
	CONSTRAINT uq_payroll_worker_week UNIQUE (worker_id, week_ending), 
	FOREIGN KEY(worker_id) REFERENCES workers (id)
);

-- Table: users
CREATE TABLE users (
	id INTEGER NOT NULL, 
	username VARCHAR(80) NOT NULL, 
	name VARCHAR(120), 
	email VARCHAR(120), 
	phone VARCHAR(30), 
	role VARCHAR(30) NOT NULL, 
	linked_worker_id INTEGER, 
	password_hash VARCHAR(256) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	must_change_password BOOLEAN NOT NULL, 
	last_login_at DATETIME, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (username), 
	FOREIGN KEY(linked_worker_id) REFERENCES workers (id)
);

-- Table: audit_logs
CREATE TABLE audit_logs (
	id INTEGER NOT NULL, 
	user_id INTEGER, 
	username VARCHAR(80) NOT NULL, 
	action VARCHAR(100) NOT NULL, 
	details TEXT, 
	ip_address VARCHAR(45), 
	timestamp DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

-- Table: cctv_recordings
CREATE TABLE cctv_recordings (
	recording_id INTEGER NOT NULL, 
	camera_id INTEGER, 
	attendance_id INTEGER, 
	trigger_type VARCHAR(20) NOT NULL, 
	recording_path VARCHAR(255) NOT NULL, 
	start_time DATETIME NOT NULL, 
	end_time DATETIME, 
	duration_seconds FLOAT, 
	file_size_bytes BIGINT, 
	storage_location VARCHAR(20) NOT NULL, 
	cloud_url VARCHAR(500), 
	uploaded_to_cloud BOOLEAN NOT NULL, 
	uploaded_at DATETIME, 
	PRIMARY KEY (recording_id), 
	FOREIGN KEY(camera_id) REFERENCES cctv_feeds (feed_id), 
	FOREIGN KEY(attendance_id) REFERENCES attendance (attendance_id)
);

-- Table: event_snapshots
CREATE TABLE event_snapshots (
	snapshot_id INTEGER NOT NULL, 
	attendance_id INTEGER NOT NULL, 
	camera_id INTEGER, 
	snapshot_type VARCHAR(20) NOT NULL, 
	file_path VARCHAR(255) NOT NULL, 
	cloud_url VARCHAR(500), 
	captured_at DATETIME NOT NULL, 
	PRIMARY KEY (snapshot_id), 
	FOREIGN KEY(attendance_id) REFERENCES attendance (attendance_id), 
	FOREIGN KEY(camera_id) REFERENCES cctv_feeds (feed_id)
);

