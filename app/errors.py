"""Lỗi HTML cho trang web; lỗi JSON thống nhất cho /api/."""
from flask import g, jsonify, render_template, request
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException

from .extensions import db

MESSAGES = {
    400: ("Yêu cầu chưa hợp lệ", "Kiểm tra nội dung vừa nhập và thử lại."),
    401: ("Cần đăng nhập", "Vui lòng đăng nhập để tiếp tục."),
    403: ("Không thể truy cập", "Bạn chưa có quyền thực hiện thao tác này."),
    404: ("Không tìm thấy trang", "Đường dẫn này không tồn tại hoặc chưa được triển khai."),
    405: ("Thao tác không phù hợp", "Phương thức gửi yêu cầu không được hỗ trợ."),
    413: ("Nội dung quá dài", "Hãy rút ngắn nội dung rồi gửi lại."),
    415: ("Định dạng chưa phù hợp", "API cần nội dung JSON."),
    429: ("Bạn thao tác hơi nhanh", "Vui lòng đợi một phút rồi thử lại."),
    503: ("Ứng dụng cần hoàn tất thiết lập", "Hoàn tất cập nhật database trước khi đăng nhập."),
    500: ("Có lỗi khi xử lý", "Hãy thử lại hoặc quay về trang tổng quan."),
}


def api_error(code, message, status=400):
    return jsonify(ok=False, error={"code": code, "message": message},
                   request_id=g.request_id), status


def register_error_handlers(app):
    @app.errorhandler(CSRFError)
    def csrf_failed(_error):
        if request.path.startswith("/api/"):
            return api_error("CSRF_INVALID", "Phiên gửi đã hết hạn. Tải lại trang rồi thử lại.", 400)
        return render_template("errors/error.html", status=400,
                               title="Phiên gửi đã hết hạn",
                               message="Tải lại trang rồi thử lại."), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        title, message = MESSAGES.get(error.code, ("Không thể xử lý", "Hãy thử lại sau."))
        if error.code == 503:
            message = error.description
        if request.path.startswith("/api/"):
            response, status = api_error(f"HTTP_{error.code}", message, error.code)
        else:
            response, status = render_template("errors/error.html", status=error.code,
                                              title=title, message=message), error.code
        # Giữ header giao thức (ví dụ Allow của lỗi 405).
        headers = {key: value for key, value in error.get_headers()
                   if key.lower() not in ("content-type", "content-length")}
        return response, status, headers

    @app.errorhandler(500)
    def internal_error(_error):
        db.session.rollback()
        if request.path.startswith("/api/"):
            return api_error("INTERNAL_ERROR", MESSAGES[500][1], 500)
        return render_template("errors/error.html", status=500,
                               title=MESSAGES[500][0], message=MESSAGES[500][1]), 500
