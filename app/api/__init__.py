"""API nội bộ dùng cùng ứng dụng Flask và CSRF."""
from flask import Blueprint

api = Blueprint("api", __name__)
from . import routes  # noqa: E402,F401
