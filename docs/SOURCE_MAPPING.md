# Đối chiếu tài liệu học phần

Bản hiện tại: Patient RAG + AI Tutor. Các mục bước 1–3 phía dưới ghi lịch sử triển khai.


Đã đọc trực tiếp hai HTML do người học cung cấp. Bộ này kế thừa cách tổ chức, viết lại cho MedQuest; không yêu cầu clone Microblog để chạy.

| Nguồn | Nội dung kế thừa | Áp dụng trong MedQuest |
|---|---|---|
| Chương 7, mục 1–2 | Config classes, Application Factory, `init_app()` | `config.py`, `app/__init__.py`, `app/extensions.py` |
| Chương 7, mục 2–3 | Blueprint, import route sau khi tạo Blueprint | `main`, `simulation`, `api` |
| Chương 7, mục 3 | Error handler cấp ứng dụng | `register_error_handlers()` phân HTML/JSON |
| Chương 7, mục 4 | Entry point, shell context, CLI | `medquest.py`, `app/cli.py` |
| Chương 7, mục 5 | unittest và cấu hình testing | `tests/test_foundation.py`, SQLite thư mục tạm |
| Micro project, mục 6 | `create_app`, SQLAlchemy, Migrate, LoginManager | Extensions gắn bằng `init_app`; bước 2 thêm User và lệnh tạo admin, chưa có đăng nhập web |
| Micro project, mục 7 | Template inheritance, blocks, `url_for` | `base.html`, các template con và tài nguyên local |
| Micro project, phần cấu trúc | `app/`, templates/static, module nghiệp vụ | Bổ sung simulation và services theo thiết kế MedQuest |

## Những điều chỉnh có chủ đích

- Không dùng `requirements.txt` cũ của chương 7 (Flask 0.12.2); dùng bộ thư viện đã cài và kiểm tra cho Python 3.12.
- Không dùng Flask-Bootstrap cũ; nạp Bootstrap 5.3.8 CSS cục bộ.
- Đặt extension trong `extensions.py` để route/service import an toàn.
- `SECRET_KEY` không có giá trị dùng chung được hardcode cho development/demo. Script tạo khóa riêng; testing có khóa chỉ dùng trong test.
- Cấu hình môi trường được đọc ở thời điểm tạo app để nhiều app không dùng chung giá trị đã chụp lúc import.
- Factory không tạo bảng, gọi AI, tải mô hình hay nhập dữ liệu. Bước 2 dùng migration `0001_p0` và lệnh tạo admin/nhập ca riêng.
- Không thêm Mail/Moment/Babel/Redis/Celery ở bước nền vì chưa có chức năng cần dùng.
- Bước 2 đã thêm `models/`, account/case service và migration; `auth/`, `cases/`, `evaluations/`, `scenario/`, `admin/` được thêm khi đến bước nghiệp vụ.

## Các tài liệu chính thức đã đối chiếu

- [Flask Application Factories](https://flask.palletsprojects.com/en/stable/patterns/appfactories/)
- [Flask-SQLAlchemy Quick Start](https://flask-sqlalchemy.palletsprojects.com/en/stable/quickstart/)
- [Flask-Migrate](https://flask-migrate.readthedocs.io/en/latest/)

Đối chiếu ngày 21/10/2026; các phiên bản thực tế nằm trong `requirements.txt`.

## Bổ sung ở bước 2 (26/10/2026)

- Kế thừa model và quy trình `flask db init → migrate → upgrade` trong hai HTML. Gói đã chứa migration nên người dùng chỉ chạy `upgrade`.
- Dùng package `models` thay cho một tệp lớn theo thiết kế MedQuest, không sao chép các bảng Post/Follow của Microblog.
- User có hai vai trò cố định, không cần bảng Role của ví dụ chương 7.
- FK ghép, chỉ mục có điều kiện và trigger SQLite theo ERD; import case có giao dịch và JSON Schema.
- Tài liệu đối chiếu thêm: [SQLAlchemy constraints](https://docs.sqlalchemy.org/en/21/core/constraints.html), [SQLite foreign keys](https://www.sqlite.org/foreignkeys.html), [SQLite partial indexes](https://www.sqlite.org/partialindex.html).

## Bổ sung ở bước 3 (26/10/2026)

| Nguồn mẫu | Áp dụng |
|---|---|
| Chương 7, bài tập Authentication Blueprint | Thêm `auth/` và `admin/`, đăng ký từ Factory |
| Micro project, mục 7 — LoginForm/RegistrationForm | Flask-WTF, validation, `hidden_tag()` và template kế thừa |
| Micro project, mục 9 — Authentication Flow | `user_loader`, `login_user`, `logout_user`, `current_user`, `login_required` |
| Chương 7, bài tập phân quyền/phân trang | Decorator admin, kiểm tra chủ sở hữu và danh sách 20 người/trang |
| Hai tài liệu, kiểm thử cấu hình testing | Test HTTP thật với CSRF và SQLite tạm; subprocess kiểm tra script nâng cấp |

Những điểm điều chỉnh so với ví dụ học phần:

- Cookie phiên Flask **được ký, không mã hóa**; không lưu mật khẩu hay hồ sơ ẩn vào cookie.
- Định danh Flask-Login có `id:auth_version` để thu hồi phiên khi đổi mật khẩu/khóa tài khoản.
- `next.startswith('/')` đơn lẻ chưa đủ: chặn thêm `//`, dấu gạch ngược, ký tự điều khiển và mã hóa lồng.
- Đăng xuất dùng POST có CSRF; API chưa đăng nhập trả JSON 401.
- Quyền ADMIN không cho đọc hội thoại riêng của người khác. Form đăng ký luôn tạo STUDENT phía server.
- Dùng `db.select()`/`db.session.get()` thay các ví dụ Query.get cũ; không thêm remember-me, email reset hoặc sửa hồ sơ ngoài phạm vi P0 hiện tại.

Đối chiếu tài liệu API: [Flask-Login 0.6.3](https://flask-login.readthedocs.io/en/0.6.3/) (đúng phiên bản cài), [Flask-WTF CSRF](https://flask-wtf.readthedocs.io/en/latest/csrf/). Các mục bước 1–2 phía trên mô tả lịch sử triển khai; phần auth/admin đã được bổ sung trong bản bước 3 này.


## Bổ sung Patient RAG và AI Tutor — 29/10/2026

Đã đọc thêm `03-flask_micro_project_advanced_LLM_RAG.html` do giảng viên Nguyễn Thị Mỹ Linh cung cấp. Tài liệu trình bày chia đoạn → embedding → bảng SQLite → truy hồi top-k cosine + từ khóa → prompt có ngữ cảnh → LLM trả lời và trích nguồn.

| Nội dung học phần | Áp dụng trong MedQuest |
|---|---|
| Package AI độc lập, cấu hình provider bằng biến môi trường | `app/ai/`, `app/ai/settings.py`, `.env` riêng |
| Chia đoạn, vector và metadata trong SQLite | `chunking.py`, `embeddings.py`, `vectorstore.py`, model `AIChunk`/bảng `ai_chunks` |
| Truy hồi kết hợp vector và từ khóa | `app/ai/rag.py`; lọc đúng phiên bản ca và dữ kiện được phép |
| Prompt ngữ cảnh, LLM qua API, câu trả lời có nguồn | `llm.py`, `patient_dialogue.py`; dùng lịch sử để hỏi tiếp tự nhiên |
| Không đủ nguồn thì không tự bịa kiến thức | Đầu ra Patient kiểm tra nguồn; dữ kiện chưa biết không tự thành phủ định |
| Kiểm tra bằng mock, tách khỏi việc đo chất lượng AI | Các test RAG/Patient/Tutor; không dùng số test phần mềm thay cho đánh giá bằng LLM thật |
| Đọc dữ liệu DB rồi đưa vào LLM | Tutor đọc đúng rubric, toàn bộ hội thoại và tổng kết của lượt; kiểm chứng dẫn chứng, code tính điểm |

Tutor là phần mở rộng nghiệp vụ của MedQuest, không phải một chức năng chấm điểm được chép nguyên từ ví dụ Microblog. Vì đã biết chính xác lượt và phiên bản ca, Tutor truy vấn DB theo ID thay vì dùng tìm kiếm vector để lấy thiếu hội thoại. Patient vẫn giữ pipeline RAG theo câu hỏi.

Điều chỉnh so với tài liệu: nguồn là ca giả lập thay cho bài đăng/tài liệu của Microblog; SQLite có bảng `ai_chunks` số nhiều; không sao chép nguyên tên route hoặc bộ embedding demo của giáo trình. Tính phù hợp về kiến trúc không đồng nghĩa toàn bộ bài tập đo chất lượng trong giáo trình đã được nghiệm thu.


## Bổ sung bộ bốn ca — 30/10/2026

Bốn JSON tại `data/curriculum` được nhập thành `CaseVersion`/`RubricCriterion`. Việc lập chỉ mục đọc database, tạo đoạn và lưu embedding ở `ai_chunks`; hội thoại lọc theo phiên bản ca và quyền tiết lộ trước khi gửi ngữ cảnh cho LLM. Các bước này giữ kiến trúc RAG của tài liệu HTML thứ ba. CLI `catalog install` điều phối nhập/index/phát hành, không thay database bằng câu trả lời hardcode.

Bệnh sử mới được soạn riêng và có danh mục nguồn ở `FOUR_CASES.md`; không gán nội dung mới cho tài liệu của giảng viên.
