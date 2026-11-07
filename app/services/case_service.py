"""Nhập phiên bản bất biến; phát hành học phần qua catalog_service riêng."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from flask import current_app
from jsonschema import Draft202012Validator

from ..extensions import db
from ..models import AuditLog, Case, CaseVersion, RubricCriterion, User

GROUP_WEIGHTS = {"CURRENT": 30, "RELATED": 20, "COMMUNICATION": 20, "REASONING": 20, "SUMMARY": 10}
PORTRAITS = {"male_student": "images/patient-student.png", "female_adult": "images/patient-female.png",
            "male_student_outpatient": "images/patient-an.png", "female_adult_outpatient": "images/patient-linh.png",
            "male_worker": "images/patient-minh.png", "female_teacher": "images/patient-huong.png"}


class CaseValidationError(ValueError):
    pass


def package_hash(package):
    raw = json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CaseValidationError(f"JSON chứa khóa lặp: {key}.")
        result[key] = value
    return result


def _reject_constant(value):
    raise CaseValidationError(f"JSON chứa số không hợp lệ: {value}.")


def load_package(path):
    path = Path(path)
    if path.stat().st_size > 1024 * 1024:
        raise CaseValidationError("Mỗi tệp ca tối đa 1 MB.")
    try:
        package = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_pairs,
                             parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CaseValidationError(f"{path.name}: JSON/UTF-8 không hợp lệ.") from exc
    validate_package(package)
    return package


def validate_package(package):
    root = Path(current_app.root_path).parent
    schema = json.loads((root / "data/schema/case.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(package), key=lambda e: str(list(e.path)))
    if errors:
        first = errors[0]
        location = ".".join(map(str, first.absolute_path)) or "gói ca"
        raise CaseValidationError(f"{location}: {first.message}")
    content = package["content"]
    if not package["demo_only"] and content.get("delivery", {}).get("scope") != "COURSEWORK":
        raise CaseValidationError("Ca không phải demo cần khai báo phạm vi COURSEWORK.")
    if content.get("delivery") and (package["demo_only"] or content.get("dialogue", {}).get("mode") != "OPEN_PATIENT"):
        raise CaseValidationError("Ca học phần phải dùng hội thoại LLM và không gắn demo_only.")

    def ids(items, key):
        values = [x[key] for x in items]
        if len(values) != len(set(values)):
            raise CaseValidationError(f"Trùng mã {key}.")
        return set(values)

    fact_ids = ids(content["facts"], "fact_id")
    state_ids = ids(content["states"], "state_id")
    intent_ids = ids(content["intents"], "intent_id")
    ids(content["rules"], "rule_id")
    ids(content["actions"], "action_code")
    ids(package["rubric"], "criterion_code")
    ids(content["development_tests"], "test_id")
    ids(content["branch_paths"], "path_id")
    events = intent_ids | {"SUBMIT", "ABANDON"}
    emitted = {r["emit_event"] for r in content["rules"]}
    terminal = {s["state_id"] for s in content["states"] if s["terminal"]}
    if not terminal:
        raise CaseValidationError("Ca cần trạng thái kết thúc.")

    def refs(values, allowed, label):
        if not set(values) <= allowed:
            raise CaseValidationError(f"{label}: tham chiếu không tồn tại {sorted(set(values)-allowed)}.")

    def snapshot(value):
        refs([value["state_id"]], state_ids - terminal, "Trạng thái đầu")
        refs(value["revealed_fact_ids"], fact_ids, "Dữ kiện đầu")
        refs(value["event_codes"], emitted, "Sự kiện đã ghi")

    snapshot(content["initial_state"])
    if set(content["initial_state"]["revealed_fact_ids"]) != {f["fact_id"] for f in content["facts"] if f["disclosure"]["mode"] == "INITIAL"}:
        raise CaseValidationError("Dữ kiện mở đầu phải khớp đúng nhóm INITIAL.")
    for fact in content["facts"]:
        dis = fact["disclosure"]
        refs(dis["intent_ids"], intent_ids, "Ý định của dữ kiện")
        refs(dis["state_ids"], state_ids - terminal, "Trạng thái của dữ kiện")
        if dis["mode"] != "INITIAL" and not dis["intent_ids"]:
            raise CaseValidationError("Dữ kiện hỏi mới tiết lộ cần ý định hợp lệ.")
    for intent in content["intents"]:
        refs(intent["fact_ids"], fact_ids, "Dữ kiện của ý định")
        for fid in intent["fact_ids"]:
            fact = next(f for f in content["facts"] if f["fact_id"] == fid)
            if intent["intent_id"] not in fact["disclosure"]["intent_ids"]:
                raise CaseValidationError("Liên kết ý định và dữ kiện phải khớp hai chiều.")
    for fact in content["facts"]:
        for iid in fact["disclosure"]["intent_ids"]:
            if fact["fact_id"] not in next(i for i in content["intents"] if i["intent_id"] == iid)["fact_ids"]:
                raise CaseValidationError("Liên kết dữ kiện và ý định phải khớp hai chiều.")
    seen_rules = []
    for rule in content["rules"]:
        refs(rule["from_states"], state_ids - terminal, "Nguồn của luật")
        if not rule["from_states"]:
            raise CaseValidationError("Luật cần ít nhất một trạng thái nguồn.")
        refs([rule["event"]], events, "Sự kiện của luật")
        refs([rule["to_state"]], state_ids | {"$same"}, "Đích của luật")
        refs(rule["reveal_fact_ids"], fact_ids, "Dữ kiện mở theo luật")
        if rule["once_event"]:
            refs([rule["once_event"]], emitted, "Sự kiện một lần")
        if rule["min_cooperation"] > rule["max_cooperation"]:
            raise CaseValidationError("Khoảng hợp tác của luật không hợp lệ.")
        for old in seen_rules:
            overlap = max(old["min_cooperation"], rule["min_cooperation"]) <= min(old["max_cooperation"], rule["max_cooperation"])
            if old["event"] == rule["event"] and old["priority"] == rule["priority"] and set(old["from_states"]) & set(rule["from_states"]) and overlap:
                raise CaseValidationError("Hai luật cùng ưu tiên trùng điều kiện; cần làm rõ trước khi nhập.")
        seen_rules.append(rule)
    branch_targets = {r["to_state"] for r in content["rules"]} - terminal - {"$same"}
    if len(branch_targets) < 2:
        raise CaseValidationError("Ca cần ít nhất hai nhánh hành vi.")
    for action in content["actions"]:
        refs([action["event"]], events, "Sự kiện hành động")
        refs(action["allowed_states"], state_ids - terminal, "Trạng thái hành động")
    for test in content["development_tests"]:
        snapshot(test["initial"])
        refs(test["intent_ids"], intent_ids, "Ý định chuẩn")
        refs(test["expected_fact_ids"], fact_ids, "Dữ kiện chuẩn")
        refs([test["expected_state"]], state_ids, "Trạng thái chuẩn")
    for path in content["branch_paths"]:
        snapshot(path["initial"])
        for step in path["steps"]:
            refs([step["event"]], events, "Sự kiện đường đi")
            refs([step["expected_state"]], state_ids, "Trạng thái đường đi")
    weights = Counter()
    for criterion in package["rubric"]:
        weights[criterion["group_code"]] += criterion["weight"]
        refs(criterion["fact_ids"], fact_ids, "Dữ kiện rubric")
    if dict(weights) != GROUP_WEIGHTS:
        raise CaseValidationError("Rubric phải đúng phân bổ 30/20/20/20/10 và tổng 100.")
    portrait = Path(current_app.static_folder) / PORTRAITS[content["patient"]["portrait_key"]]
    if not portrait.is_file():
        raise CaseValidationError("Thiếu ảnh bệnh nhân được tham chiếu.")
    return package


def import_packages(packages, admin_email):
    """Một giao dịch cho cả lô: lỗi ở ca sau rollback cả ca trước."""
    for package in packages:
        validate_package(package)
    try:
        admin = db.session.scalar(db.select(User).where(User.email_normalized == admin_email))
        if not admin or admin.role != "ADMIN" or not admin.is_active:
            raise CaseValidationError("Cần email quản trị viên ACTIVE đã tạo bằng create-admin.")
        results = []
        for package in packages:
            case = db.session.scalar(db.select(Case).where(Case.case_code == package["case_code"]))
            if case is None:
                case = Case(case_code=package["case_code"], created_by_id=admin.id)
                db.session.add(case)
                db.session.flush()
            existing = db.session.scalar(db.select(CaseVersion).where(CaseVersion.case_id == case.id, CaseVersion.version_no == package["version_no"]))
            digest = package_hash(package)
            if existing:
                if existing.content_hash != digest:
                    raise CaseValidationError(f"{case.case_code} v{package['version_no']}: nội dung đã khác. Tăng version_no; không ghi đè bản cũ.")
                results.append((case.case_code, package["version_no"], "Đã có, giữ nguyên"))
                continue
            version = CaseVersion(case_id=case.id, version_no=package["version_no"], created_by_id=admin.id,
                                  title=package["title"], status="DRAFT", demo_only=int(package["demo_only"]),
                                  content_json=package["content"], review_json=package["review"], content_hash=digest)
            db.session.add(version)
            db.session.flush()
            for index, item in enumerate(package["rubric"], 1):
                db.session.add(RubricCriterion(case_version_id=version.id, criterion_code=item["criterion_code"],
                    group_code=item["group_code"], weight=item["weight"], description=item["description"], sort_no=index,
                    levels_json={"levels":item["levels"], "fact_ids":item["fact_ids"], "evidence_sources":item["evidence_sources"]}))
            db.session.add(AuditLog(actor_user_id=admin.id, entity_type="CASE_VERSION", entity_id=str(version.id),
                                   action="CASE_IMPORTED", metadata_json={"case_code":case.case_code,"version_no":version.version_no,"status":"DRAFT","content_hash":digest}))
            results.append((case.case_code, package["version_no"], "Đã nhập DRAFT · Chưa phát hành"))
        db.session.commit()
        return results
    except Exception:
        db.session.rollback()
        raise
