"""Blueprint giao diện phòng mô phỏng."""
from flask import Blueprint

simulation = Blueprint("simulation", __name__)
from . import routes  # noqa: E402,F401
