from functools import lru_cache
import hashlib
import os
from urllib.parse import urlsplit

import numpy as np
from flask import current_app

from .chunking import tokens, digest
from .errors import AIError
from .http import endpoint, post_json
from .settings import validate_settings


@lru_cache(maxsize=1)
def local_model():
    try:
        import wordllama
        from wordllama import WordLlama
        return WordLlama.load(cache_dir=os.path.dirname(wordllama.__file__), disable_download=True)
    except (ImportError, OSError, ValueError) as exc:
        raise AIError("Chưa nạp được WordLlama. Cài requirements-ai-local.txt hoặc cấu hình embedding API.", "EMBED_LOCAL_UNAVAILABLE") from exc


def normalized(values, count):
    try:
        vectors = np.asarray(values, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != count or not 1 <= vectors.shape[1] <= 8192:
            raise ValueError("shape")
        lengths = np.linalg.norm(vectors, axis=1, keepdims=True)
        if not np.isfinite(vectors).all() or not np.isfinite(lengths).all() or (lengths <= 1e-12).any():
            raise ValueError("invalid vector")
        return vectors / lengths
    except (ValueError, TypeError, OverflowError) as exc:
        raise AIError("Vector embedding không hợp lệ hoặc không khớp số đầu vào.", "EMBED_INVALID") from exc


def openai_vectors(response, count, *, allow_missing_zero=False):
    """Khôi phục duy nhất index 0 nếu có đủ bằng chứng; không đoán thứ tự batch."""
    def invalid(reason):
        raise AIError("Embedding: " + reason, "EMBED_INVALID")

    if not isinstance(response, dict):
        invalid("phản hồi phải là JSON object.")
    if "error" in response:
        invalid("provider trả trường error trong JSON dù HTTP 200. Kiểm tra lỗi ở phía provider.")
    if "data" not in response:
        if "embeddings" in response or "embedding" in response:
            invalid("phản hồi có embedding/embeddings nhưng adapter openai cần data. Kiểm tra BASE_URL và giao thức API.")
        invalid("phản hồi thiếu trường data của API tương thích OpenAI.")
    rows = response["data"]
    if not isinstance(rows, list) or len(rows) != count:
        invalid(f"data phải chứa đúng {count} phần tử tương ứng số đầu vào.")
    if any(not isinstance(row, dict) or "embedding" not in row for row in rows):
        invalid("mỗi phần tử data cần có trường embedding.")

    missing = [i for i, row in enumerate(rows) if "index" not in row]
    indices = [row["index"] for row in rows if "index" in row]
    if any(type(index) is not int or not 0 <= index < count for index in indices):
        invalid("index phải là số nguyên trong khoảng đầu vào; không nhận null, boolean hoặc chuỗi.")
    if len(set(indices)) != len(indices):
        invalid("index bị trùng; chưa thể ghép vector với đúng đoạn nguồn.")
    if missing:
        if not (allow_missing_zero and len(missing) == 1 and set(indices) == set(range(1, count))):
            invalid("thiếu index và chưa đủ bằng chứng để xác định thứ tự vector; không tự gán theo vị trí.")
        # Một đầu vào/một vector, hoặc batch có đủ 1..N-1: chỉ còn index 0.
        rows = [dict(row) for row in rows]
        rows[missing[0]]["index"] = 0
    ordered = sorted(rows, key=lambda row: row["index"])
    if [row["index"] for row in ordered] != list(range(count)):
        invalid("index không khớp các đầu vào.")
    return [row["embedding"] for row in ordered]


class Embedder:
    def __init__(self, cfg=None):
        self.cfg = dict(current_app.config if cfg is None else cfg)
        try:
            validate_settings(self.cfg)
        except ValueError as exc:
            raise AIError(str(exc), "AI_CONFIG") from exc
        self.provider = self.cfg["EMBED_PROVIDER"]
        self.model = self.cfg["EMBED_MODEL"]
        self.remote = self.provider in ("openai", "ollama")
        if self.remote and not self.model:
            raise AIError("Chưa đặt EMBED_MODEL trong .env.", "AI_CONFIG")
        if self.provider == "openai" and not self.cfg["EMBED_API_KEY"]:
            raise AIError("Chưa đặt EMBED_API_KEY hoặc LLM_API_KEY trong .env.", "AI_CONFIG")
        if self.remote:
            endpoint(self.cfg["EMBED_BASE_URL"], "")

    @property
    def identity(self):
        if self.provider == "local":
            return "local:wordllama-l2-256:v1"
        if self.provider == "test":
            return "test:hash-256:v1"
        # Cùng tên model trên hai máy chủ có thể là hai không gian vector khác nhau.
        return self.provider + ":" + digest([self.cfg["EMBED_BASE_URL"].rstrip("/"), self.model])

    def embed(self, texts):
        if not texts or len(texts) > 32 or any(not isinstance(t, str) or not t.strip() or len(t) > 12000 for t in texts):
            raise AIError("Lô embedding chưa hợp lệ; tối đa 32 đoạn/lần.", "EMBED_INPUT")
        if self.provider == "local":
            vectors = local_model().embed(texts)
        elif self.provider == "test":
            vectors = np.zeros((len(texts), 256), dtype=np.float32)
            for row, value in enumerate(texts):
                for word in tokens(value) or {"empty"}:
                    index = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % 256
                    vectors[row, index] += 1
        else:
            suffix = "embeddings" if self.provider == "openai" else "api/embed"
            payload = {"model": self.model, "input": texts}
            if self.provider == "ollama":
                payload["truncate"] = False
            response = post_json(endpoint(self.cfg["EMBED_BASE_URL"], suffix), payload,
                                 self.cfg["EMBED_API_KEY"], self.cfg["AI_HTTP_TIMEOUT"])
            if self.provider == "openai":
                base = urlsplit(self.cfg["EMBED_BASE_URL"])
                is_gemini = (base.hostname == "generativelanguage.googleapis.com"
                             and base.path.rstrip("/") == "/v1beta/openai")
                vectors = openai_vectors(response, len(texts), allow_missing_zero=is_gemini)
            else:
                if "error" in response or "embeddings" not in response:
                    raise AIError("Embedding Ollama: phản hồi có error hoặc thiếu embeddings.", "EMBED_INVALID")
                vectors = response["embeddings"]
        return normalized(vectors, len(texts))
