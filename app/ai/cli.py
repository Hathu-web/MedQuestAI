from copy import deepcopy
import click
from flask import Blueprint, current_app
from ..extensions import db
from ..models import AIChunk, CaseVersion
from .embeddings import Embedder
from .errors import AIError
from .llm import LLMClient
from .rag import plan_turn
from .vectorstore import ensure_schema, index_case, load_index
from . import patient_dialogue

ai = Blueprint("ai", __name__)


def cli_error(function):
    from functools import wraps
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (AIError, ValueError) as exc:
            db.session.rollback()
            raise click.ClickException(str(exc)) from exc
    return wrapped


@ai.cli.command("status")
@cli_error
def status():
    embedder, llm = Embedder(), LLMClient()
    click.echo(f"AI_CHAT_ENABLED={current_app.config['AI_CHAT_ENABLED']}")
    click.echo(f"LLM: {llm.provider}; model={current_app.config['LLM_MODEL'] or '(demo)'}")
    click.echo(f"Embedding: {embedder.identity}")
    click.echo("Đây là kiểm tra cấu hình; chưa gọi mạng và chưa xác nhận API key.")
    ensure_schema()
    rows = db.session.execute(db.select(AIChunk.case_version_id, AIChunk.embedding_identity, db.func.count())
        .group_by(AIChunk.case_version_id, AIChunk.embedding_identity)).all()
    for version_id, identity, count in rows:
        click.echo(f"case_version_id={version_id} | {identity} | {count} đoạn")
    if not rows:
        click.echo("Chưa có chỉ mục. Chạy: python -m flask --app medquest ai index-cases")


@ai.cli.command("index-cases")
@click.option("--version-id", type=click.IntRange(min=1), help="Bỏ trống để index mọi phiên bản ca.")
@cli_error
def index_cases(version_id):
    embedder = Embedder()
    query = db.select(CaseVersion.id).order_by(CaseVersion.id)
    if version_id is not None:
        query = query.where(CaseVersion.id == version_id)
    ids = list(db.session.scalars(query))
    db.session.rollback()
    if not ids:
        raise click.ClickException("Không tìm thấy phiên bản ca để index.")
    for identifier in ids:
        count = index_case(identifier, embedder)
        click.echo(f"OK: case_version_id={identifier}, {count} đoạn, {embedder.identity}")
    click.echo("Index xong. Chạy lại với cùng cấu hình sẽ thay chỉ mục của ca, không nhân đôi đoạn.")


@ai.cli.command("check-provider")
@cli_error
def check_provider():
    """Gọi thật một embedding và một phản hồi ngắn (nếu chọn backend API)."""
    embedder, client = Embedder(), LLMClient()
    vector = embedder.embed(["Dữ liệu kiểm tra kết nối."])
    result = client.answer("Đây là dữ liệu gì?", {"name": "Mẫu", "age": 22, "self_pronoun": "tôi"},
                           [{"text": "Đây là dữ liệu kiểm tra kết nối."}])
    click.echo(f"OK: embedding {vector.shape[1]} chiều; phản hồi {result['mode']}; nguồn hợp lệ.")


@ai.cli.command("evaluate")
@click.option("--version-id", type=click.IntRange(min=1))
@cli_error
def evaluate(version_id):
    """Kiểm tra retrieval với câu ví dụ có sẵn; không chấm chất lượng LLM."""
    embedder, cfg = Embedder(), dict(current_app.config)
    ids = [version_id] if version_id else list(db.session.scalars(db.select(CaseVersion.id).order_by(CaseVersion.id)))
    total = passed = 0
    for identifier in ids:
        version = db.session.get(CaseVersion, identifier)
        if not version:
            raise click.ClickException("Không tìm thấy phiên bản ca.")
        rows, content = load_index(version, embedder), deepcopy(version.content_json)
        db.session.rollback()
        cases = content["development_tests"]
        vectors = []
        for offset in range(0, len(cases), 32):
            vectors.extend(embedder.embed([test["question"] for test in cases[offset:offset + 32]]))
        for test, vector in zip(cases, vectors):
            snapshot = {"content": content, "rows": rows, "before": test["initial"]}
            is_open = patient_dialogue.enabled(content)
            plan = (patient_dialogue.plan_patient_turn(snapshot, test["question"], [vector], cfg) if is_open
                    else plan_turn(snapshot, test["question"], vector, cfg))
            found = {h["source_id"] for h in plan["hits"]}
            expected = set(test["expected_fact_ids"])
            ok = ((expected <= found if expected else not found) if is_open else
                  found == expected and plan["result"]["state"]["state_id"] == test["expected_state"])
            total += 1
            passed += int(ok)
            click.echo(f"{identifier}/{test['test_id']}: {'PASS' if ok else 'FAIL'} | expected={sorted(expected)} found={sorted(found)}")
    click.echo(f"Retrieval/điều kiện trên bộ ví dụ của ca: {passed}/{total}.")
    click.echo("Đây là kiểm tra hồi quy; cần đánh giá thêm câu diễn đạt mới và câu trả lời LLM thật.")
    click.echo("Ca OPEN_PATIENT kiểm tra tìm đủ nguồn yêu cầu trong top-k; chưa đánh giá giao tiếp hoặc độ đúng của câu LLM.")
    if not total or passed != total:
        raise click.ClickException("Chỉ mục/cấu hình retrieval chưa đạt toàn bộ tình huống chuẩn.")
