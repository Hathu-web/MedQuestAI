# MedQuest AI — bốn bệnh nhân, RAG và AI Tutor

Bản `08-four-patient-curriculum`: 4 ca riêng, 2 nam và 2 nữ; hội thoại tự do với LLM, truy xuất dữ liệu từng ca từ SQLite, lưu tiến trình và chấm theo rubric 100 điểm. Nhân vật/bệnh sử là hư cấu phục vụ học tập. Schema vẫn `0003_rag`; không cần migration mới cho bộ ca này.

## Đang cập nhật từ bản Tutor chạy được

Giữ `.env`, database, tài khoản và model/API key đang chạy. Chép **nội dung** thư mục `medquest_ai` trong gói vào thư mục có `medquest.py` đang dùng. Không lồng thêm một tầng `medquest_ai`, không xóa folder cũ, không chạy setup lại.

Trong `.env` tại đúng thư mục này, bảo đảm có một dòng cho mỗi khóa:

```dotenv
AI_CHAT_ENABLED=true
AI_TUTOR_ENABLED=true
AI_TOP_K=6
AI_MAX_CONTEXT_CHARS=4000
AI_TUTOR_MAX_OUTPUT_TOKENS=6144
```

Giữ các dòng model, base URL, API key và đường dẫn database hiện tại. Từ terminal đã kích hoạt venv, đứng tại thư mục chứa `medquest.py`:

```powershell
python -c "import medquest; print(medquest.__file__)"
python -m flask --app medquest check --db
python -m flask --app medquest catalog install --admin-email admin@medquest.local
python -m flask --app medquest run --port 5001
```

Nếu admin dùng email khác, thay đúng email đó; không thay bằng tên hiển thị. Lệnh `catalog install` tự sao lưu database đang cấu hình, nhập phiên bản mới, gọi embedding API để lập chỉ mục, rồi mở cả bốn ca cho học viên. Nếu lỗi mạng, sửa lỗi và chạy lại cùng lệnh; chỉ mục hợp lệ được dùng lại. Lệnh có thể phát sinh chi phí embedding. Không gọi LLM để thử toàn bộ hội thoại.

Đăng nhập **tài khoản học viên** để mở lượt **Thực hành** và lưu điểm vào thống kê. Tài khoản admin vẫn dùng lượt kiểm tra `TEST`, cùng LLM nhưng không trộn điểm với học viên. Có thể đăng ký một tài khoản học viên riêng bằng nút Đăng ký; không đổi quyền hoặc xóa admin cũ. Xem [FOUR_CASES.md](docs/FOUR_CASES.md) để biết cấu trúc và cách nghiệm thu.

## Bốn ca trong thư viện

| Nhân vật | Tình huống | Trọng tâm |
|---|---|---|
| Nguyễn Văn An · Nam · 22 | Mệt mỏi, khó tập trung | Mô tả triệu chứng, sinh hoạt, triệu chứng đi kèm |
| Trần Ngọc Linh · Nữ · 28 | Tiểu buốt, đi tiểu nhiều | Câu hỏi nhạy cảm, quyền riêng tư, tiền sử |
| Lê Quốc Minh · Nam · 45 | Đau lưng sau bê hàng | Đặc điểm đau, ảnh hưởng lao động, sàng lọc dấu hiệu cần chú ý |
| Phạm Thu Hương · Nữ · 40 | Nóng rát vùng thượng vị sau ăn | Mối liên hệ bữa ăn/tư thế, triệu chứng cảnh báo, thuốc |

Thư viện hiển thị một phiên bản đang dùng cho mỗi ca, ưu tiên bản đã phát hành. Các phiên bản cũ của An/Linh được lưu trữ, lịch sử vẫn gắn đúng ca và rubric cũ; không tự chấm lại hay đổi điểm đã lưu.

## Cài mới khi chưa có database

Dùng Python 3.12:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\setup_database.py
```

Script hỏi mật khẩu admin, không có mật khẩu mặc định. Sau đó điền cấu hình LLM/embedding thật trong `.env`, bật Patient/Tutor và dùng các thông số truy xuất ở trên. Chỉ đặt model được tài khoản của bạn hỗ trợ; giữ model đang chạy thành công nếu đã có.

```powershell
.\.venv\Scripts\python.exe -m flask --app medquest ai check-provider
.\.venv\Scripts\python.exe -m flask --app medquest catalog install --admin-email admin@medquest.local
.\.venv\Scripts\python.exe -m flask --app medquest run --port 5001
```

`check-provider` có gọi API. Bộ bốn ca không mở lượt bằng provider demo, embedding test/local, thiếu index hoặc khi Patient/Tutor bị tắt. Không tự thay bằng câu trả lời mẫu nếu API hỏng.

## Từng thư mục chịu trách nhiệm gì?

| Vị trí | Công việc |
|---|---|
| `medquest.py` | Entry point gọi application factory |
| `config.py`, `app/__init__.py`, `app/extensions.py` | Môi trường, extensions và blueprint; không tự tạo DB |
| `app/auth/`, `app/admin/` | Đăng nhập, mật khẩu, quyền và trạng thái tài khoản |
| `app/cases/`, `app/main/` | Thư viện, nhiệm vụ, dashboard, hướng dẫn |
| `app/simulation/`, `app/api/` | Hội thoại, tổng kết và API kiểm tra chủ sở hữu |
| `app/models/` | Tài khoản, ca, lượt, tin nhắn, đánh giá và nhật ký AI |
| `app/services/catalog_service.py`, `app/catalog.py` | Cài bốn ca, kiểm tra chỉ mục, phát hành học phần và lưu audit |
| `app/services/scenario_engine.py` | Trạng thái hợp tác và điều kiện chia sẻ thông tin |
| `app/services/assessment_service.py` | Lấy bài/rubric từ DB, gọi Tutor, xác minh và lưu điểm |
| `app/ai/` | Chia đoạn, embedding, tìm nguồn, prompt, adapter LLM và kiểm tra đầu ra |
| `app/templates/`, `app/static/` | HTML/CSS/JS và ảnh; không chứa bệnh sử ẩn |
| `data/curriculum/` | Bốn ca mới, mỗi ca một JSON có bệnh sử, nhánh giao tiếp và rubric |
| `data/cases/`, `data/case_updates/` | Các bản trước, dùng hồi quy/lịch sử; không phải thư viện mới |
| `data/schema/` | JSON Schema kiểm tra dữ liệu ca |
| `migrations/` | Lịch sử schema; giữ đầy đủ |
| `tests/` | Database tạm và AI thay thế trong kiểm thử; không dùng key thật |
| `scripts/` | Cài mới, nâng cấp, sao lưu và preflight container |
| `docs/` | Bộ ca, RAG, Tutor, Docker và kết quả kiểm tra |
| `instance/`, `.env` | Dữ liệu/cấu hình riêng, không đưa vào Git hoặc image |
| `Dockerfile`, `compose.yaml`, `.dockerignore` | Đóng gói và lưu dữ liệu bên ngoài container |

## Kiểm tra và Docker

```powershell
python -m unittest discover -s tests -v
python -m pip check
python -m flask --app medquest check --db
python -m flask --app medquest db current
```

Revision: `0003_rag (head)`. Xem [VERIFICATION.md](docs/VERIFICATION.md) và [DOCKER.md](docs/DOCKER.md). Không cần Docker Desktop để chạy bản Flask này. Bộ source chứa file đóng gói; chưa có image/deployment hay thao tác push GitHub.

## Phạm vi

- Đây là bản luyện tập đồ án: hỏi bệnh với RAG + LLM, Tutor dựa trên bằng chứng, dữ liệu và kết quả lưu thật trong app.
- Phát hành `COURSEWORK` mở quyền thực hành trong app, không tự ghi là đã được bác sĩ/giảng viên duyệt. Các trường rà soát chuyên môn vẫn ghi đúng trạng thái chưa rà soát.
- Chưa có người chấm độc lập để đo độ đồng thuận của Tutor; điểm là góp ý học tập. Kiểm tra JSON/nguồn không bảo đảm mọi diễn giải của LLM đúng.
- Không có khám cơ thể, kết quả xét nghiệm phát sinh thật, kê đơn, voice hoặc nhân vật 3D. Dữ kiện chưa có không được tự suy ra.
- SQLite và cấu hình Docker một worker phù hợp phạm vi đồ án nhỏ; chưa kiểm thử tải nhiều người hoặc tên miền/HTTPS.
