"""Dữ liệu UI minh họa, KHÔNG phải Scenario Engine hay AI Patient thật.

Chỉ dùng trong /preview; không có bệnh án thật, chẩn đoán hay kết quả chấm.
Sẽ giữ tách biệt khi bổ sung services/patient_service.py ở giai đoạn sau.
"""
import unicodedata


PROFILES = {
    "male": {"name": "Nguyễn Văn An", "age": 45, "initials": "NA", "gender": "Nam", "address": "Anh",
             "image": "images/patient-room.png", "reason": "Cảm thấy không khỏe",
             "opening": "Chào bác sĩ, hôm nay tôi thấy không khỏe."},
    "female": {"name": "Trần Ngọc Linh", "age": 28, "initials": "NL", "gender": "Nữ", "address": "Chị",
               "image": "images/patient-female.png", "reason": "Cảm thấy mệt và khó tập trung",
               "opening": "Dạo này tôi thấy mệt và khó tập trung, tôi muốn được trao đổi thêm."},
}


def patient_profile(patient_key="male"):
    if patient_key not in PROFILES:
        raise ValueError("Không có mẫu bệnh nhân này.")
    profile = {"key": patient_key, **PROFILES[patient_key]}
    if patient_key == "female":
        profile["sample_questions"] = [
            ("Thời điểm", "Chị bắt đầu thấy mệt từ khi nào?"),
            ("Ảnh hưởng", "Tình trạng mệt ảnh hưởng đến sinh hoạt của chị thế nào?"),
            ("Mối lo", "Điều gì khiến chị lo lắng nhất?"),
        ]
    else:
        profile["sample_questions"] = [
            ("Thời điểm", "Anh bắt đầu thấy khó chịu từ khi nào?"),
            ("Vị trí", "Anh thấy khó chịu ở vị trí nào?"),
            ("Mối lo", "Điều gì khiến anh lo lắng nhất?"),
        ]
    return profile


def sample_reply(text, patient_key="male"):
    patient_profile(patient_key)
    normalized = "".join(c for c in unicodedata.normalize("NFD", text.lower())
                         if unicodedata.category(c) != "Mn").replace("đ", "d")
    fact = None
    if any(word in normalized for word in ("tu khi", "khi nao", "bat dau", "bao lau")):
        timing = "đầu tuần này" if patient_key == "female" else "sáng nay"
        symptom = "mệt" if patient_key == "female" else "khó chịu"
        reply = f"Tôi bắt đầu thấy {symptom} từ {timing}."
        fact = {"key": "onset", "label": "Thời điểm bắt đầu", "value": f"Từ {timing}"}
    elif patient_key == "female" and any(word in normalized for word in ("anh huong", "tap trung", "sinh hoat")):
        reply = "Tôi thấy khó tập trung khi sắp xếp công việc."
        fact = {"key": "impact", "label": "Ảnh hưởng", "value": "Khó tập trung khi sắp xếp công việc"}
    elif any(word in normalized for word in ("o dau", "vi tri", "cho nao")):
        if patient_key == "female":
            reply = "Trong mẫu giao diện này, tôi chưa có thông tin về vị trí khó chịu cụ thể."
        else:
            reply = "Tôi thấy khó chịu ở vùng bụng, nhưng chưa biết diễn tả rõ hơn."
            fact = {"key": "location", "label": "Vị trí khó chịu", "value": "Vùng bụng"}
    elif any(word in normalized for word in ("lo lang", "lo nhat", "cam thay", "lo dieu")):
        reply = "Tôi lo vì chưa biết chuyện gì đang xảy ra. Tôi mong bác sĩ giải thích dễ hiểu."
        fact = {"key": "concern", "label": "Mối quan tâm", "value": "Muốn được giải thích dễ hiểu"}
    elif any(word in normalized for word in ("xin chao", "chao anh", "chao chi", "cam on", "toi hieu")):
        reply = "Cảm ơn bác sĩ. Tôi sẽ cố gắng kể rõ những gì mình cảm thấy."
    else:
        topic = "ảnh hưởng đến sinh hoạt" if patient_key == "female" else "vị trí khó chịu"
        reply = f"Trong mẫu hội thoại này, bác sĩ có thể hỏi tôi về thời điểm bắt đầu, {topic} hoặc điều tôi đang lo lắng."
    return {"role": "patient", "text": reply, "fact": fact, "preview_only": True}
