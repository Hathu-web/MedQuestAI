"""Từ câu hỏi -> ý định -> luật -> đoạn được phép -> LLM -> nguồn được lưu."""
from copy import deepcopy
from ..services import fake_patient
from ..services.scenario_engine import apply_event
from .vectorstore import search


def select_intent(content, rows, question, vector, cfg):
    normalized = fake_patient.normalize(question)
    if any(phrase in normalized for phrase in ("rubric", "system prompt", "toan bo du kien an", "bo qua moi quy tac")):
        return None
    known = fake_patient.detect_intent(content, question)
    if known:
        return known
    # Ý hỏi rõ nhưng ca chưa có dữ kiện, hoặc câu chứa nhiều ý: không dùng
    # độ giống vector để đổi sang một ý khác (ví dụ vị trí -> thời điểm).
    if fake_patient.intent_candidates(content, question):
        return None
    # WordLlama chủ yếu tiếng Anh; với local demo chỉ dùng nhận diện cơ bản.
    if cfg["EMBED_PROVIDER"] in ("local", "test"):
        return None
    allowed = {intent["intent_id"] for intent in content["intents"]}
    ranked = search(rows, question, vector, kind="INTENT", allowed_ids=allowed,
                    top_k=len(rows), alpha=cfg["AI_HYBRID_ALPHA"], min_score=cfg["AI_INTENT_MIN_SCORE"])
    scores = {}
    for hit in ranked:
        scores.setdefault(hit["source_id"], hit["score"])
    ranked_intents = sorted(scores, key=lambda key: -scores[key])
    if not ranked_intents:
        return None
    if len(ranked_intents) > 1 and scores[ranked_intents[0]] - scores[ranked_intents[1]] < cfg["AI_INTENT_MARGIN"]:
        return None
    return ranked_intents[0]


def plan_turn(snapshot, question, vector, cfg):
    content = snapshot["content"]
    intent = select_intent(content, snapshot["rows"], question, vector, cfg)
    result = apply_event(content, snapshot["before"], intent)
    allowed = {fact["fact_id"] for fact in result["facts"]}
    hits = search(snapshot["rows"], question, vector, kind="FACT", allowed_ids=allowed,
                  top_k=cfg["AI_TOP_K"], alpha=cfg["AI_HYBRID_ALPHA"], min_score=cfg["AI_MIN_SCORE"])
    selected, used = [], 0
    for hit in hits:
        if used + len(hit["text"]) > cfg["AI_MAX_CONTEXT_CHARS"]:
            continue
        selected.append(hit)
        used += len(hit["text"])
    return {"intent": intent, "result": result, "hits": selected}


def finish_turn(snapshot, plan, response=None):
    content, result, hits = snapshot["content"], plan["result"], plan["hits"]
    sources = []
    if response is None:
        answer = fake_patient.reply({"intent": plan["intent"], "facts": [],
            "opening": content["public"]["opening"], "fallbacks": content["fallbacks"]})
        # Nếu biết ý định nhưng truy xuất không có kết quả, không nói đã có dữ kiện.
        if result["facts"]:
            answer = content["fallbacks"]["unknown"]
        mode = "rule"
    else:
        answer, mode = response["answer"], response["mode"]
        for number in response["citations"]:
            hit = hits[number - 1]
            sources.append({"n": number, "case_version_id": snapshot["case_version_id"],
                "fact_id": hit["source_id"], "part": hit["part"], "text": hit["text"],
                "label": f"{snapshot['case_code']} v{snapshot['version_no']} · {hit['source_id']}",
                "source_hash": hit["source_hash"], "score": round(hit["score"], 4)})
    after = deepcopy(result["state"])
    after["revealed_fact_ids"] = list(snapshot["before"].get("revealed_fact_ids", []))
    for source in sources:
        if source["fact_id"] not in after["revealed_fact_ids"]:
            after["revealed_fact_ids"].append(source["fact_id"])
    return {"answer": answer, "after": after, "sources": sources, "mode": mode,
            "intent": plan["intent"], "rule_id": result["rule_id"], "events": result["event_codes"]}
