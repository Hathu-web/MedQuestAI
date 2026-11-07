"""Chia theo từng fact: không gộp dữ kiện có quyền tiết lộ khác nhau."""
import hashlib
import json
import re
import unicodedata


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def tokens(value):
    value = unicodedata.normalize("NFD", value.lower().replace("đ", "d"))
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    stop = {"toi", "ban", "anh", "chi", "em", "la", "va", "co", "cua", "cho", "thi", "mot", "duoc"}
    return {word for word in re.findall(r"[a-z0-9]+", value) if word not in stop}


def split_text(value, size=500, overlap=80):
    if not 0 <= overlap < size:
        raise ValueError("Overlap cần nhỏ hơn kích thước đoạn.")
    value = " ".join(value.split())
    start = 0
    while start < len(value):
        end = min(start + size, len(value))
        if end < len(value):
            boundary = value.rfind(" ", start + size // 2, end)
            if boundary > start:
                end = boundary
        yield value[start:end]
        if end == len(value):
            break
        start = max(start + 1, end - overlap)


def case_documents(content):
    documents = []
    for intent in content["intents"]:
        for number, example in enumerate(intent["examples"]):
            documents.append({"kind": "INTENT", "source_id": intent["intent_id"], "part": number,
                              "text": example, "search_text": example})
    for fact in content["facts"]:
        examples = " ".join(example for intent in content["intents"]
            if fact["fact_id"] in intent["fact_ids"] for example in intent["examples"])
        if fact.get("search_hints"):
            examples += "\n" + " ".join(fact["search_hints"])
        for number, chunk in enumerate(split_text(fact["value"])):
            documents.append({"kind": "FACT", "source_id": fact["fact_id"], "part": number,
                              "text": chunk, "search_text": examples + "\n" + chunk})
    if not documents or len(documents) > 600:
        raise ValueError("Mỗi phiên bản ca cần từ 1 đến 600 đoạn chỉ mục.")
    return documents
