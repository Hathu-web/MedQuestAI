"""Điểm chạy tương ứng flasky.py/microblog.py trong tài liệu môn học."""
from app import create_app
from app.extensions import db

app = create_app()


@app.shell_context_processor
def shell_context():
    return {"db": db}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
