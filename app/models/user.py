from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from .common import utc_now


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email_normalized = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.Text, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="STUDENT")
    status = db.Column(db.String(16), nullable=False, default="ACTIVE")
    is_test_account = db.Column(db.Integer, nullable=False, default=0)
    # Tăng khi đổi mật khẩu hoặc khóa/mở tài khoản để thu hồi cookie cũ.
    auth_version = db.Column(db.Integer, nullable=False, default=1, server_default=db.text("1"))
    created_at = db.Column(db.String(32), nullable=False, default=utc_now)
    __table_args__ = (
        db.CheckConstraint("role IN ('STUDENT','ADMIN')", name="role"),
        db.CheckConstraint("status IN ('ACTIVE','LOCKED')", name="status"),
        db.CheckConstraint("is_test_account IN (0,1)", name="test_flag"),
        db.CheckConstraint("length(trim(email_normalized)) > 0", name="email_not_blank"),
    )

    @property
    def is_active(self):
        return self.status == "ACTIVE"

    def get_id(self):
        return f"{self.id}:{self.auth_version}"

    def set_password(self, password):
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            raise ValueError("Mật khẩu cần từ 12 đến 128 ký tự.")
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
