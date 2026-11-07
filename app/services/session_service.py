"""Đọc lượt đã lưu; trả các trường công khai cho HTML/API."""
from flask import current_app
import re
from ..extensions import db
from ..models import CaseVersion, Message, Submission, SessionEvent
from .practice_service import public_case
from .scenario_engine import action_options


def public_session(item):
    version = db.session.get(CaseVersion, item.case_version_id)
    messages = db.session.scalars(db.select(Message).where(Message.session_id == item.id).order_by(Message.seq_no)).all()
    content = version.content_json
    revealed = set(item.state_json.get("revealed_fact_ids", []))
    submission = db.session.get(Submission, item.id)
    evidence = {e.evidence_payload_json.get("operation_id"): e.evidence_payload_json
                for e in db.session.scalars(db.select(SessionEvent).where(SessionEvent.session_id == item.id))}
    def message_data(message):
        metadata = evidence.get(message.operation_id, {}) if message.sender == "PATIENT" else {}
        return {"id": message.id, "seq_no": message.seq_no, "sender": message.sender,
                "text": message.content_text, "created_at": message.created_at,
                "display_text": (re.sub(r"\s*\[\d+\]", "", message.content_text)
                    if metadata.get("reply_mode") == "rag_patient" else message.content_text),
                "reply_mode": metadata.get("reply_mode", "fake"),
                "sources": [{k: source[k] for k in ("n", "label", "text")} for source in metadata.get("sources", [])]}
    extra = {}
    if item.status == "COMPLETED":
        from .assessment_service import public_assessment
        extra["assessment"] = public_assessment(item)
    return {
        **extra,
        "id": item.id, "status": item.status, "mode": item.mode,
        "state_version": item.state_version, "turn_index": item.turn_index,
        "started_at": item.started_at, "ended_at": item.ended_at,
        "case": public_case(version),
        **({"dialogue_mode": "OPEN_PATIENT"} if content.get("dialogue", {}).get("mode") == "OPEN_PATIENT" else {}),
        "provider": ("rag_demo" if current_app.config["LLM_PROVIDER"] == "demo" else "rag_llm")
                    if current_app.config.get("AI_CHAT_ENABLED") else "fake", "max_turns": 20,
        "can_send": item.status == "ACTIVE" and item.turn_index < 20,
        "facts": [{key: fact[key] for key in ("fact_id", "topic", "value", "knowledge")}
                  for fact in content["facts"] if fact["fact_id"] in revealed],
        "actions": [{"code": row["action_code"], "label": row["label"]}
                    for row in action_options(content, item.state_json)] if item.status == "ACTIVE" else [],
        "summary": submission.summary_json.get("text", "") if submission else None,
        "messages": [message_data(m) for m in messages],
    }
