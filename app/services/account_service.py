"""Nghiệp vụ tài khoản; route không nhận role từ biểu mẫu đăng ký."""
import re
import unicodedata

from email_validator import EmailNotValidError, validate_email
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import AuditLog, User

# Hash chỉ dùng cân bằng chi phí kiểm tra khi email không tồn tại; không có tài khoản tương ứng.
DUMMY_HASH = "scrypt:32768:8:1$9APeauuw7ZVHBXuV$d4d475c22d2144b53e7f95024a50a2bf815f7808afcbd344236f522a058ac54f6ffe66b5979bf45e29cfe7a77662ae3d66f761686f75d590481936cad6b80ade"


def normalize_email(value):
    if not isinstance(value, str):
        raise ValueError("Email không hợp lệ.")
    email = unicodedata.normalize("NFKC", value).strip().casefold()
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Email không hợp lệ.")
    return email


def normalize_registration_email(value):
    email = normalize_email(value)
    try:
        return validate_email(email, check_deliverability=False).normalized.casefold()
    except EmailNotValidError as exc:
        raise ValueError("Email không hợp lệ. Ví dụ: ten@example.com.") from exc


def register_student(email, display_name, password):
    email = normalize_registration_email(email)
    name = display_name.strip()
    if not 1 <= len(name) <= 100:
        raise ValueError("Tên hiển thị cần từ 1 đến 100 ký tự.")
    if not password.strip():
        raise ValueError("Mật khẩu không được chỉ gồm dấu cách.")
    try:
        user = User(email_normalized=email, display_name=name, role="STUDENT", status="ACTIVE", is_test_account=0)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        db.session.add(AuditLog(actor_user_id=user.id, entity_type="USER", entity_id=str(user.id),
                               action="STUDENT_REGISTERED", metadata_json={"role":"STUDENT"}))
        db.session.commit()
        return user
    except IntegrityError as exc:
        db.session.rollback()
        raise ValueError("Email này đã được đăng ký. Hãy dùng email khác hoặc đăng nhập.") from exc
    except Exception:
        db.session.rollback()
        raise


def authenticate(email, password):
    email = normalize_email(email)
    user = db.session.scalar(db.select(User).where(User.email_normalized == email))
    valid = check_password_hash(user.password_hash if user else DUMMY_HASH, password)
    if not user or not valid or not user.is_active:
        return None
    return user


def change_password(user_id, expected_version, current_password, new_password):
    try:
        user = db.session.get(User, user_id, populate_existing=True)
        if not user or not user.is_active or user.auth_version != expected_version:
            raise ValueError("Phiên đăng nhập đã thay đổi. Vui lòng đăng nhập lại.")
        if not user.check_password(current_password):
            raise ValueError("Mật khẩu hiện tại chưa đúng.")
        if not 12 <= len(new_password) <= 128 or not new_password.strip():
            raise ValueError("Mật khẩu mới cần 12–128 ký tự, không chỉ dấu cách.")
        if user.check_password(new_password):
            raise ValueError("Hãy chọn mật khẩu mới khác mật khẩu hiện tại.")
        old_hash = user.password_hash
        new_hash = generate_password_hash(new_password, method="scrypt")
        result = db.session.execute(db.update(User).where(
            User.id == user_id, User.auth_version == expected_version,
            User.status == "ACTIVE", User.password_hash == old_hash
        ).values(password_hash=new_hash, auth_version=User.auth_version + 1))
        if result.rowcount != 1:
            raise ValueError("Tài khoản vừa thay đổi. Vui lòng đăng nhập lại.")
        db.session.add(AuditLog(actor_user_id=user_id, entity_type="USER", entity_id=str(user_id),
                               action="PASSWORD_CHANGED", metadata_json={"sessions_revoked":True}))
        db.session.commit()
        return db.session.get(User, user_id)
    except Exception:
        db.session.rollback()
        raise


def set_student_status(actor_id, actor_version, user_id, desired, expected_status):
    """Chỉ quản lý trạng thái STUDENT. Không cấp quyền và không sửa mật khẩu."""
    if desired not in {"ACTIVE", "LOCKED"} or expected_status not in {"ACTIVE", "LOCKED"}:
        raise ValueError("Trạng thái không hợp lệ.")
    try:
        actor = db.session.get(User, actor_id, populate_existing=True)
        if not actor or actor.role != "ADMIN" or not actor.is_active or actor.auth_version != actor_version:
            raise PermissionError("Không có quyền quản trị.")
        target = db.session.get(User, user_id)
        if not target or target.role != "STUDENT" or target.id == actor.id:
            raise LookupError("Không tìm thấy tài khoản học viên.")
        if target.status != expected_status:
            raise ValueError("Trạng thái tài khoản vừa thay đổi. Tải lại trang trước khi thực hiện.")
        if target.status == desired:
            db.session.rollback()
            return
        result = db.session.execute(db.update(User).where(
            User.id == user_id, User.role == "STUDENT", User.status == expected_status
        ).values(status=desired, auth_version=User.auth_version + 1))
        if result.rowcount != 1:
            raise ValueError("Trạng thái tài khoản vừa thay đổi. Tải lại trang trước khi thực hiện.")
        db.session.add(AuditLog(actor_user_id=actor_id, entity_type="USER", entity_id=str(user_id),
                               action="ACCOUNT_STATUS_CHANGED", metadata_json={"before":expected_status,"after":desired}))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def create_admin(email, display_name, password):
    email = normalize_email(email)
    name = display_name.strip()
    if not 1 <= len(name) <= 100:
        raise ValueError("Tên hiển thị cần từ 1 đến 100 ký tự.")
    try:
        existing = db.session.scalar(db.select(User).where(User.email_normalized == email))
        if existing:
            raise ValueError("Email đã tồn tại; không tự đổi quyền, mật khẩu hay mở khóa tài khoản.")
        admin = User(email_normalized=email, display_name=name, role="ADMIN", status="ACTIVE", is_test_account=1)
        admin.set_password(password)
        db.session.add(admin)
        db.session.flush()
        db.session.add(AuditLog(actor_user_id=admin.id, entity_type="USER", entity_id=str(admin.id),
                               action="ADMIN_CREATED", metadata_json={"role":"ADMIN","is_test_account":True}))
        db.session.commit()
        return admin
    except Exception:
        db.session.rollback()
        raise
