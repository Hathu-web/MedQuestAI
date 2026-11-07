from flask_wtf import FlaskForm
from wtforms import HiddenField, PasswordField, StringField, SubmitField
from wtforms.validators import EqualTo, InputRequired, Length, ValidationError

from ..services.account_service import normalize_email, normalize_registration_email


def not_blank(_form, field):
    if not field.data or not field.data.strip():
        raise ValidationError("Vui lòng nhập nội dung, không chỉ dấu cách.")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[InputRequired("Nhập email của bạn."), Length(max=254)])
    password = PasswordField("Mật khẩu", validators=[InputRequired("Nhập mật khẩu."), Length(max=128)])
    next = HiddenField(validators=[Length(max=2048)])
    submit = SubmitField("Đăng nhập")

    def validate_email(self, field):
        try:
            field.data = normalize_email(field.data)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc


class RegistrationForm(FlaskForm):
    display_name = StringField("Tên hiển thị", filters=[lambda v: v.strip() if v else v],
        validators=[InputRequired("Nhập tên hiển thị."), Length(min=1, max=100, message="Tên tối đa 100 ký tự."), not_blank])
    email = StringField("Email", validators=[InputRequired("Nhập email của bạn."), Length(max=254)])
    password = PasswordField("Mật khẩu", validators=[InputRequired("Nhập mật khẩu."),
        Length(min=12, max=128, message="Mật khẩu cần từ 12 đến 128 ký tự."), not_blank])
    password_confirm = PasswordField("Nhập lại mật khẩu", validators=[InputRequired("Nhập lại mật khẩu."),
        Length(max=128), EqualTo("password", message="Hai mật khẩu chưa khớp.")])
    submit = SubmitField("Tạo tài khoản học viên")

    def validate_email(self, field):
        try:
            field.data = normalize_registration_email(field.data)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc


class PasswordForm(FlaskForm):
    current_password = PasswordField("Mật khẩu hiện tại", validators=[InputRequired("Nhập mật khẩu hiện tại."), Length(max=128)])
    password = PasswordField("Mật khẩu mới", validators=[InputRequired("Nhập mật khẩu mới."),
        Length(min=12, max=128, message="Mật khẩu cần từ 12 đến 128 ký tự."), not_blank])
    password_confirm = PasswordField("Nhập lại mật khẩu mới", validators=[InputRequired("Nhập lại mật khẩu mới."),
        Length(max=128), EqualTo("password", message="Hai mật khẩu mới chưa khớp.")])
    submit = SubmitField("Lưu mật khẩu mới")
