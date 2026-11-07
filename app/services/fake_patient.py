"""Bộ phản hồi mẫu offline để thử nghiệp vụ. Không phải LLM hay RAG."""
import re
import unicodedata


def normalize(value):
    value = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", value))


# Chỉ nhận diện ý định giao tiếp; dữ kiện và câu trả lời lấy từ ca trong DB.
PHRASES = {
    "INTRO_PERMISSION": ("toi la sinh vien", "xin phep trao doi", "dong y trao doi"),
    "EMPATHY": ("toi hieu", "minh hieu", "toi lang nghe", "toi rat tiec"),
    "PRIVACY_PERMISSION": ("quyen rieng tu", "chon dieu minh muon chia se", "hoi them duoc khong"),
    "PRESSURE": ("phai noi ngay", "dung vong vo", "bat buoc phai noi"),
    "SUMMARY_CONFIRM": ("tom tat", "hieu dung chua"),
    "ASK_ONSET": ("tu khi nao", "bao lau", "bat dau luc nao"),
    "ASK_DESCRIPTION": ("mo ta cu the", "cam giac met", "cam giac kho chiu",
                        "met nhu the nao", "met nhu nao", "met the nao", "met ra sao", "met kieu gi",
                        "met moi nhu the nao", "met moi ra sao", "met moi kieu gi"),
    "ASK_LOCATION": ("met o dau", "met cho nao", "met vung nao", "vi tri met",
                     "vi tri kho chiu", "dau o dau", "dau cho nao", "vi tri dau",
                     "bo phan nao bi met", "cho nao bi met", "met moi o dau",
                     "met o vi tri nao", "met o bo phan nao", "met tap trung o dau"),
    "ASK_IMPACT": ("anh huong", "kho tap trung", "sinh hoat"),
    "ASK_SLEEP": ("ngu", "giac ngu"),
    "ASK_CONTEXT": ("viec hoc", "cong viec", "ky thi", "lich lam viec"),
    "ASK_CONCERN": ("lo lang", "lo nhat", "lo ngai"),
    "ASK_MEDICATION": ("thuoc", "vien uong"),
    "ASK_EXPECTATION": ("mong muon", "mong doi", "ky vong"),
    "OPEN_QUESTION": ("den day", "ke them", "ly do den"),
}


def intent_candidates(content, question):
    """Giữ cả ý hỏi ca chưa hỗ trợ để RAG không ép sang ý định gần nhất."""
    normalized = normalize(question)
    # Ví dụ của ca là nguồn chuẩn, ưu tiên trước bộ từ khóa đơn giản.
    exact = {row["intent_id"] for row in content["intents"]
             if any(normalize(example) == normalized for example in row["examples"])}
    if exact:
        return exact
    padded = f" {normalized} "
    return {intent for intent, phrases in PHRASES.items()
            if any(f" {phrase} " in padded for phrase in phrases)}


def detect_intent(content, question):
    matches = intent_candidates(content, question)
    available = {row["intent_id"] for row in content["intents"]}
    # Không suy đoán nhiều ý định hoặc tự thực hiện SUBMIT/ABANDON từ câu chat.
    if len(matches) == 1:
        intent = next(iter(matches))
        return intent if intent in available else None
    return None


def reply(context):
    """Chỉ nhận ngữ cảnh đã lọc; không nhận toàn bộ facts/rubric của ca."""
    facts = context["facts"]
    if facts:
        return "\n".join(row["value"] for row in facts)
    fallback = context["fallbacks"]
    intent = context["intent"]
    if intent == "ASK_CONCERN" or intent == "PRESSURE":
        return fallback["guarded"]
    if intent == "OPEN_QUESTION":
        return context["opening"]
    if intent == "INTRO_PERMISSION":
        return "Tôi đồng ý trao đổi với bạn."
    if intent == "EMPATHY":
        return "Cảm ơn bạn đã lắng nghe."
    if intent == "PRIVACY_PERMISSION":
        return "Cảm ơn bạn đã giải thích. Tôi đồng ý trao đổi thêm."
    if intent == "SUMMARY_CONFIRM":
        return "Bạn có thể nhắc lại để tôi xác nhận từng ý."
    return fallback["unknown"] + " " + fallback["unclear"]
