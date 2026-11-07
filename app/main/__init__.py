"""Blueprint trang tổng quan và hướng dẫn."""
from flask import Blueprint

main = Blueprint("main", __name__)
from . import routes  # noqa: E402,F401
