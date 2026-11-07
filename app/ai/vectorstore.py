"""Vector float32 little-endian trong SQLite; lọc quyền TRƯỚC khi xếp hạng."""
from copy import deepcopy
import numpy as np
from sqlalchemy import inspect, text

from ..extensions import db
from ..models import AIChunk, CaseVersion
from .chunking import case_documents, digest, tokens
from .errors import AIError


def ensure_schema():
    if "ai_chunks" not in inspect(db.engine).get_table_names():
        raise AIError("Chưa nâng database bước 6. Dừng server và chạy scripts/upgrade_step6.py.", "RAG_SCHEMA")


def index_case(version_id, embedder):
    ensure_schema()
    version = db.session.get(CaseVersion, version_id)
    if not version:
        raise AIError("Không tìm thấy phiên bản ca.", "CASE_NOT_FOUND", 404)
    content, content_hash = deepcopy(version.content_json), version.content_hash
    documents = case_documents(content)
    source_hash = digest(documents)
    db.session.rollback()  # Không giữ giao dịch trong lúc gọi embedding.
    parts = [embedder.embed([d["search_text"] for d in documents[start:start + 32]])
             for start in range(0, len(documents), 32)]
    try:
        vectors = np.concatenate(parts, axis=0)
    except ValueError as exc:
        raise AIError("Các lô embedding khác số chiều.", "EMBED_INVALID") from exc
    try:
        db.session.execute(text("BEGIN IMMEDIATE"))
        latest = db.session.get(CaseVersion, version_id, populate_existing=True)
        if latest.content_hash != content_hash or digest(case_documents(latest.content_json)) != source_hash:
            raise AIError("Ca vừa thay đổi khi đang index. Chạy lại lệnh index.", "RAG_SOURCE_CHANGED", 409)
        db.session.execute(db.delete(AIChunk).where(AIChunk.case_version_id == version_id))
        for document, vector in zip(documents, vectors):
            db.session.add(AIChunk(case_version_id=version_id, kind=document["kind"], source_id=document["source_id"],
                part=document["part"], content_text=document["text"], search_text=document["search_text"],
                source_hash=source_hash, embedding_identity=embedder.identity, dimensions=len(vector),
                vector_blob=vector.astype("<f4").tobytes()))
        db.session.commit()
        return len(documents)
    except Exception:
        db.session.rollback()
        raise


def load_index(version, embedder):
    ensure_schema()
    expected = case_documents(version.content_json)
    expected_hash = digest(expected)
    rows = db.session.scalars(db.select(AIChunk).where(AIChunk.case_version_id == version.id)
        .order_by(AIChunk.kind, AIChunk.source_id, AIChunk.part)).all()
    wanted = {(d["kind"], d["source_id"], d["part"]): d for d in expected}
    if len(rows) != len(wanted):
        raise AIError("Chưa có chỉ mục đầy đủ cho ca. Chạy flask ai index-cases.", "RAG_INDEX_MISSING")
    result = []
    for row in rows:
        key = row.kind, row.source_id, row.part
        source = wanted.get(key)
        if (not source or row.source_hash != expected_hash or row.embedding_identity != embedder.identity
                or row.content_text != source["text"] or row.search_text != source["search_text"]):
            raise AIError("Chỉ mục cũ hoặc khác model embedding. Chạy lại flask ai index-cases.", "RAG_INDEX_STALE")
        if len(row.vector_blob) != row.dimensions * 4:
            raise AIError("Vector đã lưu không hợp lệ. Chạy lại lệnh index.", "RAG_INDEX_INVALID")
        vector = np.frombuffer(row.vector_blob, dtype="<f4")
        norm = np.linalg.norm(vector)
        if len(vector) != row.dimensions or not np.isfinite(vector).all() or not np.isclose(norm, 1, atol=1e-3):
            raise AIError("Vector đã lưu không hợp lệ. Chạy lại lệnh index.", "RAG_INDEX_INVALID")
        result.append({**source, "case_version_id": version.id, "vector": vector.copy(), "source_hash": expected_hash})
    return result


def search(rows, query, qvec, *, kind, allowed_ids, top_k, alpha, min_score):
    selected = [r for r in rows if r["kind"] == kind and r["source_id"] in allowed_ids]
    if not selected:
        return []
    if any(len(r["vector"]) != len(qvec) for r in selected):
        raise AIError("Số chiều embedding đã thay đổi. Index lại trước khi chat.", "RAG_DIMENSION")
    qtokens = tokens(query)
    result = []
    for row in selected:
        semantic = float(np.clip(row["vector"] @ qvec, 0, 1))
        lexical = len(qtokens & tokens(row["search_text"])) / max(1, len(qtokens))
        score = alpha * semantic + (1 - alpha) * lexical
        if score >= min_score:
            result.append({**row, "score": score})
    result.sort(key=lambda r: (-r["score"], r["source_id"], r["part"]))
    return result[:top_k]
