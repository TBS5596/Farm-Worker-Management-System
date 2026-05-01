from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from database import db


class Setting(db.Model):
    """Key-value store for all system configuration (Firebase, camera, org name)."""
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<Setting {self.key}={self.value}>"


class User(db.Model):
    """Admin accounts for the dashboard."""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    role = db.Column(db.String(30), default="supervisor", nullable=False)
    linked_worker_id = db.Column(db.Integer, db.ForeignKey("workers.id"), nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"


class AuditLog(db.Model):
    """System-wide audit trail of all admin actions."""
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    username = db.Column(db.String(80), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<AuditLog {self.username} {self.action} @ {self.timestamp}>"


class Worker(db.Model):
    """Farm worker profiles."""
    __tablename__ = "workers"

    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    nrc_number = db.Column(db.String(20), unique=True, nullable=True)
    pin_hash = db.Column(db.String(256), nullable=False)
    pin_fingerprint = db.Column(db.String(64), nullable=True)
    fingerprint_template = db.Column(db.LargeBinary, nullable=True)
    phone_number = db.Column(db.String(30), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    emergency_contact = db.Column(db.String(120), nullable=True)
    department = db.Column(db.String(80), nullable=True)
    enrollment_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="active", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    def set_pin(self, pin: str) -> None:
        self.pin_hash = generate_password_hash(pin)

    def check_pin(self, pin: str) -> bool:
        return check_password_hash(self.pin_hash, pin)

    def __repr__(self):
        return f"<Worker {self.worker_id} – {self.name}>"


class Attendance(db.Model):
    """Compatibility table from Workers.sql for check-in/check-out sessions."""
    __tablename__ = "attendance"

    attendance_id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("workers.id"), nullable=False)
    check_in_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    check_out_time = db.Column(db.DateTime, nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    verified_by_cctv = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"<Attendance {self.attendance_id} worker={self.worker_id}>"


class CCTVFeed(db.Model):
    __tablename__ = "cctv_feeds"

    feed_id = db.Column(db.Integer, primary_key=True)
    camera_name = db.Column(db.String(50), nullable=False)
    camera_location = db.Column(db.String(100), nullable=True)
    rtsp_url = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default="offline", nullable=False)
    last_heartbeat = db.Column(db.DateTime, nullable=True)


class Payroll(db.Model):
    __tablename__ = "payroll"

    payroll_id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("workers.id"), nullable=False)
    week_ending = db.Column(db.Date, nullable=False)
    total_hours = db.Column(db.Float, nullable=True)
    hourly_rate = db.Column(db.Float, nullable=True)
    gross_pay = db.Column(db.Float, nullable=True)
    napsa_deduction = db.Column(db.Float, nullable=True)
    nhima_deduction = db.Column(db.Float, nullable=True)
    net_pay = db.Column(db.Float, nullable=True)
    paid_status = db.Column(db.String(20), default="pending", nullable=False)
    payment_date = db.Column(db.Date, nullable=True)


class BiometricDevice(db.Model):
    __tablename__ = "biometric_devices"

    device_id = db.Column(db.Integer, primary_key=True)
    device_name = db.Column(db.String(50), nullable=False)
    device_serial = db.Column(db.String(100), unique=True, nullable=True)
    device_type = db.Column(db.String(20), default="fingerprint", nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    usb_port = db.Column(db.String(20), nullable=True)
    status = db.Column(db.String(20), default="offline", nullable=False)
    last_heartbeat = db.Column(db.DateTime, nullable=True)
    location = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class FaceTemplate(db.Model):
    __tablename__ = "face_templates"

    face_id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("workers.id"), nullable=False)
    face_embedding = db.Column(db.LargeBinary, nullable=False)
    reference_image_path = db.Column(db.String(255), nullable=True)
    quality_score = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=True)


class BiometricTransaction(db.Model):
    __tablename__ = "biometric_transactions"

    transaction_id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("biometric_devices.device_id"), nullable=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("workers.id"), nullable=True)
    transaction_type = db.Column(db.String(30), nullable=False)
    success = db.Column(db.Boolean, default=False, nullable=False)
    match_score = db.Column(db.Float, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class CCTVRecording(db.Model):
    __tablename__ = "cctv_recordings"

    recording_id = db.Column(db.Integer, primary_key=True)
    camera_id = db.Column(db.Integer, db.ForeignKey("cctv_feeds.feed_id"), nullable=True)
    recording_path = db.Column(db.String(255), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    file_size_bytes = db.Column(db.BigInteger, nullable=True)
    storage_location = db.Column(db.String(20), default="local", nullable=False)
    cloud_url = db.Column(db.String(500), nullable=True)
    uploaded_to_cloud = db.Column(db.Boolean, default=False, nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=True)


class EventSnapshot(db.Model):
    __tablename__ = "event_snapshots"

    snapshot_id = db.Column(db.Integer, primary_key=True)
    attendance_id = db.Column(db.Integer, db.ForeignKey("attendance.attendance_id"), nullable=False)
    camera_id = db.Column(db.Integer, db.ForeignKey("cctv_feeds.feed_id"), nullable=True)
    snapshot_type = db.Column(db.String(20), default="photo", nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    cloud_url = db.Column(db.String(500), nullable=True)
    captured_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class OfflineSyncQueue(db.Model):
    __tablename__ = "offline_sync_queue"

    sync_id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("biometric_devices.device_id"), nullable=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("workers.id"), nullable=True)
    operation_type = db.Column(db.String(50), nullable=False)
    payload = db.Column(db.Text, nullable=False)
    sync_status = db.Column(db.String(20), default="pending", nullable=False)
    retry_count = db.Column(db.Integer, default=0, nullable=False)
    last_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    synced_at = db.Column(db.DateTime, nullable=True)


class CloudSyncMetadata(db.Model):
    __tablename__ = "cloud_sync_metadata"

    sync_id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(50), nullable=False)
    record_id = db.Column(db.Integer, nullable=False)
    cloud_status = db.Column(db.String(20), default="pending", nullable=False)
    cloud_record_id = db.Column(db.String(100), nullable=True)
    last_sync_attempt = db.Column(db.DateTime, nullable=True)
    synced_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("table_name", "record_id", name="uq_cloud_sync_table_record"),
    )


class DailyAttendanceSummary(db.Model):
    __tablename__ = "daily_attendance_summary"

    summary_id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("workers.id"), nullable=False)
    summary_date = db.Column(db.Date, nullable=False)
    check_in_time = db.Column(db.Time, nullable=True)
    check_out_time = db.Column(db.Time, nullable=True)
    total_hours = db.Column(db.Float, nullable=True)
    late_minutes = db.Column(db.Integer, default=0, nullable=False)
    early_departure_minutes = db.Column(db.Integer, default=0, nullable=False)
    verified_by_cctv = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("worker_id", "summary_date", name="uq_daily_attendance_worker_day"),
    )


class HardwareHealthLog(db.Model):
    __tablename__ = "hardware_health_logs"

    log_id = db.Column(db.Integer, primary_key=True)
    device_type = db.Column(db.String(30), nullable=False)
    device_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="offline", nullable=False)
    error_code = db.Column(db.String(50), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    response_time_ms = db.Column(db.Integer, nullable=True)
    logged_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
