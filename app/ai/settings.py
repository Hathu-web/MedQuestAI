"""Đọc cấu hình AI theo factory; testing không đọc key/URL thật từ .env."""
import math

DEFAULTS = {
    "AI_CHAT_ENABLED": False,
    "AI_TUTOR_ENABLED": False,
    "AI_TUTOR_MAX_OUTPUT_TOKENS": 4096,
    "AI_TUTOR_MAX_CONTEXT_CHARS": 120000,
    "AI_TUTOR_MAX_ATTEMPTS": 3,
    "LLM_PROVIDER": "demo", "LLM_MODEL": "", "LLM_BASE_URL": "", "LLM_API_KEY": "",
    "LLM_REASONING_EFFORT": "", "EMBED_PROVIDER": "local", "EMBED_MODEL": "",
    "EMBED_BASE_URL": "", "EMBED_API_KEY": "",
    "AI_HTTP_TIMEOUT": 30, "AI_TOP_K": 4, "AI_MIN_SCORE": 0.15,
    "AI_HYBRID_ALPHA": 0.3, "AI_INTENT_MIN_SCORE": 0.4, "AI_INTENT_MARGIN": 0.08,
    "AI_MAX_CONTEXT_CHARS": 2400, "AI_MAX_OUTPUT_TOKENS": 1024,
    "AI_DAILY_CALL_LIMIT": 60,
}


def configure_ai(app, values):
    settings = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        if key not in values or values[key] is None:
            continue
        value = values[key]
        if isinstance(default, bool):
            if str(value).lower() not in ("true", "false", "1", "0"):
                raise ValueError(f"{key} cần true hoặc false.")
            settings[key] = str(value).lower() in ("true", "1")
        elif isinstance(default, int):
            settings[key] = int(value)
        elif isinstance(default, float):
            settings[key] = float(value)
        else:
            settings[key] = str(value).strip()
    settings["EMBED_API_KEY"] = settings["EMBED_API_KEY"] or settings["LLM_API_KEY"]
    settings["EMBED_BASE_URL"] = settings["EMBED_BASE_URL"] or settings["LLM_BASE_URL"]
    app.config.update(settings)


def validate_settings(cfg):
    ranges = {"AI_HTTP_TIMEOUT": (1, 120), "AI_TOP_K": (1, 8), "AI_MIN_SCORE": (0, 1),
        "AI_HYBRID_ALPHA": (0, 1), "AI_INTENT_MIN_SCORE": (0, 1), "AI_INTENT_MARGIN": (0, 1),
        "AI_MAX_CONTEXT_CHARS": (500, 8000), "AI_MAX_OUTPUT_TOKENS": (128, 4096),
        "AI_DAILY_CALL_LIMIT": (1, 10000), "AI_TUTOR_MAX_OUTPUT_TOKENS": (1024, 8192),
        "AI_TUTOR_MAX_CONTEXT_CHARS": (10000, 200000), "AI_TUTOR_MAX_ATTEMPTS": (1, 5)}
    for key, (low, high) in ranges.items():
        value = cfg[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} phải trong khoảng {low}–{high}.")
    if cfg["LLM_PROVIDER"] not in ("demo", "openai", "ollama"):
        raise ValueError("LLM_PROVIDER cần demo, openai hoặc ollama.")
    if cfg["EMBED_PROVIDER"] not in ("local", "openai", "ollama", "test"):
        raise ValueError("EMBED_PROVIDER cần local, openai hoặc ollama.")
    if cfg["EMBED_PROVIDER"] == "test" and not cfg["TESTING"]:
        raise ValueError("Embedding test chỉ dành cho unittest, không dùng để demo RAG.")
