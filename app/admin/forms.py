from flask_wtf import FlaskForm
from wtforms import HiddenField, SubmitField
from wtforms.validators import AnyOf, InputRequired


class AccountStatusForm(FlaskForm):
    status = HiddenField(validators=[InputRequired(), AnyOf(["ACTIVE", "LOCKED"])])
    expected_status = HiddenField(validators=[InputRequired(), AnyOf(["ACTIVE", "LOCKED"])])
    submit = SubmitField("Xác nhận")
