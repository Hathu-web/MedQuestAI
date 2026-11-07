from flask_wtf import FlaskForm
from wtforms import HiddenField, IntegerField, TextAreaField
from wtforms.validators import AnyOf, InputRequired, Length, NumberRange, Regexp
from wtforms.widgets import HiddenInput


class RequestForm(FlaskForm):
    request_key = HiddenField(validators=[InputRequired(), Regexp(r"^[A-Za-z0-9_-]{16,100}$")])
    expected_state_version = IntegerField(widget=HiddenInput(), validators=[
        InputRequired(), NumberRange(min=0, max=2_147_483_647)])


class MessageForm(RequestForm):
    text = TextAreaField("Câu hỏi của bạn", validators=[InputRequired(), Length(max=2000)])


class ActionForm(RequestForm):
    action_code = HiddenField(validators=[InputRequired(), Regexp(r"^[A-Z][A-Z0-9_]{0,59}$")])


class AssessmentForm(RequestForm):
    pass


class CloseForm(RequestForm):
    decision = HiddenField(validators=[InputRequired(), AnyOf(["SUBMIT", "ABANDON"])])
    summary = TextAreaField("Tóm tắt những điều bạn đã tìm hiểu", validators=[Length(max=4000)])
