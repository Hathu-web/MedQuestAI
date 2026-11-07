from flask import Blueprint

auth = Blueprint("auth", __name__)
from . import routes  # noqa: E402,F401
