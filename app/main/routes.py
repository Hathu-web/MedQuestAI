from flask import render_template
from flask_login import current_user, login_required
from . import main
from ..extensions import db
from ..models import CaseVersion, SimulationSession
from ..services.practice_service import dashboard_data


@main.get("/dashboard")
@login_required
def dashboard():
    return render_template("main/dashboard.html", title="Tổng quan học tập", active_nav="overview",
                           data=dashboard_data(current_user))


@main.get("/")
def index():
    return render_template("main/index.html", title="Tổng quan", active_nav="overview")


@main.get("/guide")
def guide():
    return render_template("main/guide.html", title="Cách sử dụng", active_nav="guide")


@main.get("/account")
@login_required
def account():
    query = db.select(SimulationSession).where(SimulationSession.user_id == current_user.id)
    if current_user.role == "ADMIN":
        query = query.where(SimulationSession.mode == "TEST")
    elif not current_user.is_test_account:
        query = query.where(SimulationSession.mode == "PRACTICE")
    rows = db.session.scalars(query.order_by(SimulationSession.started_at.desc(), SimulationSession.id.desc()).limit(5)).all()
    recent = [(row, db.session.get(CaseVersion, row.case_version_id).title) for row in rows]
    return render_template("main/account.html", title="Tài khoản của tôi", active_nav="account", recent=recent)
