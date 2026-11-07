from flask import Blueprint

cases = Blueprint("cases", __name__)

from . import routes
