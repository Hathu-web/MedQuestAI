"""Cấu hình được đọc khi tạo app, theo Application Factory của tài liệu chương 7."""
from datetime import timedelta
import os
from pathlib import Path

from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent


class Config:
    APP_NAME = "MedQuest AI"
    BUILD_STAGE = "08-four-patient-curriculum"
    SESSION_DAILY_LIMIT = 3
    DATABASE_REVISION = "0003_rag"
    AUTH_RATE_LIMIT_ENABLED = True
    AUTH_RATE_WINDOW_SECONDS = 60
    AUTH_LOGIN_LIMIT = 10
    AUTH_REGISTER_LIMIT = 5
    AUTH_PASSWORD_LIMIT = 5
    SECRET_KEY = None
    DEBUG = False
    TESTING = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 10}}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False  # Bản chạy local bằng HTTP.
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    MAX_CONTENT_LENGTH = 16 * 1024
    MAX_FORM_MEMORY_SIZE = 16 * 1024
    MAX_FORM_PARTS = 20
    PREVIEW_ENABLED = False
    PREVIEW_MAX_MESSAGE_LENGTH = 2000
    PREVIEW_MAX_TURNS = 20
    AI_CONNECTED = False
    WTF_CSRF_TIME_LIMIT = 2 * 60 * 60  # Flask-WTF nhận số giây.


class DevelopmentConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///medquest_dev.sqlite"


class TestingConfig(Config):
    TESTING = True
    PREVIEW_ENABLED = True  # Giữ kiểm thử hồi quy cho endpoint xem trước cũ.
    SECRET_KEY = "tests-only-key-never-use-outside-tests"
    SQLALCHEMY_DATABASE_URI = "sqlite:///medquest_test.sqlite"


class DemoConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///medquest_demo.sqlite"


class ProductionConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///medquest.sqlite"
    SESSION_COOKIE_SECURE = True
    PREVIEW_ENABLED = False


config = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "demo": DemoConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}


def environment_values():
    """Không sửa os.environ: mỗi app đọc một bản cấu hình độc lập."""
    values = dict(dotenv_values(BASE_DIR / ".env"))
    values.update(os.environ)
    return values
