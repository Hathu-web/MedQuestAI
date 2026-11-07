"""Một worker để limiter trong RAM và SQLite hoạt động đúng với thiết kế hiện tại."""
import os

bind = "0.0.0.0:8000"
workers = 1
worker_class = "gthread"
threads = 4
timeout = 2 * int(os.getenv("AI_HTTP_TIMEOUT", "120")) + 90
graceful_timeout = 2 * int(os.getenv("AI_HTTP_TIMEOUT", "120")) + 30
keepalive = 5
preload_app = False
accesslog = "-"
errorlog = "-"
# Không ghi query string, cookie, body hoặc Authorization vào access log.
access_log_format = '%(t)s "%(m)s %(U)s" %(s)s %(L)s'
forwarded_allow_ips = ""  # Chưa cấu hình một reverse proxy đáng tin cậy.
control_socket_disable = True
