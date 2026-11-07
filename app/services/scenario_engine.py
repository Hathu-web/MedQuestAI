"""Luật kịch bản thuần Python; content được nạp từ CaseVersion trong DB."""
from copy import deepcopy


def apply_event(content, state, event):
    """Một sự kiện chọn tối đa một luật. Không sửa content/state đầu vào."""
    after = deepcopy(state)
    after.setdefault("revealed_fact_ids", [])
    after.setdefault("event_codes", [])
    states = {row["state_id"]: row for row in content["states"]}
    if after["state_id"] not in states:
        raise ValueError("Trạng thái lượt không thuộc phiên bản ca.")
    if states[after["state_id"]]["terminal"]:
        return {"state": after, "rule_id": None, "facts": [], "event_codes": []}

    eligible = [rule for rule in content["rules"]
                if rule["event"] == event
                and after["state_id"] in rule["from_states"]
                and rule["min_cooperation"] <= after.get("cooperation", 0) <= rule["max_cooperation"]
                and (not rule["once_event"] or rule["once_event"] not in after["event_codes"])]
    rule = max(eligible, key=lambda row: row["priority"], default=None)
    emitted = []
    if rule:
        if rule["to_state"] != "$same":
            after["state_id"] = rule["to_state"]
        cooperation = rule["cooperation_set"]
        if cooperation is None:
            cooperation = after.get("cooperation", 0) + rule["cooperation_delta"]
        after["cooperation"] = max(0, min(2, cooperation))
        emitted.append(rule["emit_event"])
        if rule["emit_event"] not in after["event_codes"]:
            after["event_codes"].append(rule["emit_event"])

    intent = next((row for row in content["intents"] if row["intent_id"] == event), None)
    candidates = set(intent["fact_ids"] if intent else [])
    if rule:
        candidates.update(rule["reveal_fact_ids"])
    facts = []
    for fact in content["facts"]:
        disclosure = fact["disclosure"]
        # Luật cũng không được bỏ qua quyền tiết lộ của từng dữ kiện.
        allowed = (after["state_id"] in disclosure["state_ids"]
                   and after.get("cooperation", 0) >= disclosure["min_cooperation"]
                   and (disclosure["mode"] == "INITIAL" or event in disclosure["intent_ids"]))
        if fact["fact_id"] in candidates and allowed:
            facts.append({key: fact[key] for key in ("fact_id", "topic", "value", "knowledge")})
            if fact["fact_id"] not in after["revealed_fact_ids"]:
                after["revealed_fact_ids"].append(fact["fact_id"])
    return {"state": after, "rule_id": rule["rule_id"] if rule else None,
            "facts": facts, "event_codes": emitted}


def action_options(content, state):
    used = state.get("action_uses", {})
    return [row for row in content["actions"]
            if state["state_id"] in row["allowed_states"]
            and used.get(row["action_code"], 0) < row["max_uses"]]
