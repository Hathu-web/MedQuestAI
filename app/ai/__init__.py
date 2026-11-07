"""Package AI riêng với cấu hình, chỉ mục, truy xuất và adapter LLM."""


def register_ai(app):
    from .cli import ai
    app.register_blueprint(ai)
