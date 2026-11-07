# Hiểu bước 2: từ mã Python đến dữ liệu SQLite

## Kết quả của bước này

Ở bước 1, Flask dựng trang và trả lời theo mẫu. Bước 2 tạo nền dữ liệu để các bước sau có thể lưu người dùng, ca, lượt thực hành và kết quả. **Có model không có nghĩa màn hình nghiệp vụ đã hoạt động**: chat preview vẫn chưa ghi lịch sử, đăng nhập sẽ làm ở bước 3.

Hai ảnh nam/nữ xem trước giúp thử giao diện ngay. Mỗi hồ sơ chọn một `image` và `initials`; JavaScript gửi `patient_key` trong danh mục cố định. Không nhận đường dẫn ảnh tùy ý từ người dùng.

## 1. Factory nối các phần như thế nào?

`medquest.py` gọi `create_app()` trong `app/__init__.py`. Factory đọc `config.py`, gắn các extension qua `init_app`, import `app.models`, gắn Blueprint và các lệnh CLI.

Import model chỉ đưa định nghĩa bảng vào `db.metadata`. Nó không tạo bảng trong file SQLite. Khi chạy `python -m flask --app medquest db upgrade`, Alembic mới đọc migration và tạo schema. Đây là quy trình `init → migrate → upgrade` từ hai tài liệu mẫu; hai thao tác đầu đã được thực hiện khi chuẩn bị mã nguồn.

Không gọi `db.create_all()` trong app hoặc mỗi lần mở trang: cách đó không quản lý được lịch sử đổi schema và không cài các trigger bổ sung của migration này.

## 2. Vì sao có 14 bảng?

| Nhóm | Model / bảng | Dữ liệu lưu |
|---|---|---|
| Tài khoản | User / users | Email chuẩn hóa, mật khẩu băm, vai trò, khóa tài khoản |
| Ca | Case / cases | Mã ca ổn định |
| Phiên bản ca | CaseVersion / case_versions | Nội dung JSON, trạng thái, rà soát và mã băm |
| Rubric | RubricCriterion / rubric_criteria | Tiêu chí, trọng số, mức đạt và loại bằng chứng |
| Lượt học | SimulationSession / sessions | Chủ lượt, phiên bản ca cố định, trạng thái và khóa chống trùng |
| Hội thoại | Message / messages | Chỉ các tin đã được chấp nhận |
| Sự kiện | SessionEvent / session_events | Hành động và trạng thái trước/sau |
| Bản nộp | Submission / submissions | Một bản tổng kết bất biến cho mỗi lượt hoàn tất |
| Lần chấm | Evaluation / evaluations | Mỗi lần chấm/chấm lại riêng, trạng thái và tổng điểm hợp lệ |
| Điểm tiêu chí | EvaluationItem / evaluation_items | Mức đạt, điểm và lý do theo rubric đúng phiên bản |
| Dẫn chứng | Evidence / evidence | Nguồn tin nhắn, hành động hoặc trường của bản nộp |
| Thao tác AI | AIOperation / ai_operations | Một yêu cầu logic, request_key và phiên bản trạng thái dự kiến |
| Lần gọi API | AICall / ai_calls | Mỗi cuộc gọi vật lý, token, chi phí dự phòng/thực tế |
| Kiểm toán | AuditLog / audit_log | Ai tạo admin/nhập ca, mã đối tượng và metadata đã giới hạn |

Bảng `alembic_version` là bảng kỹ thuật do Alembic quản lý; vì vậy công cụ xem SQLite sẽ thấy **15 bảng**, gồm 14 bảng nghiệp vụ và 1 bảng migration.

Một thao tác AI có thể cần nhận diện ý định rồi diễn đạt hoặc thử lại, nên operation khác call. Một bản nộp có thể được chấm lại, nên submission khác evaluation. Đổi rubric phải tạo phiên bản mới, không làm biến đổi lượt cũ.

## 3. Khóa ngoại ghép giải quyết việc gì?

Nếu chỉ kiểm tra `message_id` tồn tại thì vẫn có thể gắn tin của lượt A vào điểm của lượt B. Migration dùng cặp `(message_id, session_id)` để database từ chối liên kết đó.

Tương tự, item kiểm tra `(criterion_id, case_version_id)` và bộ `(evaluation_id, session_id, case_version_id)`. Dẫn chứng liên kết với item, message, event cùng lượt; bản nộp làm nguồn phải có `submission_session_id == session_id`. Mỗi dẫn chứng chỉ chọn đúng một loại nguồn.

`PRAGMA foreign_keys=ON` được bật cho mỗi kết nối SQLite. Các test dùng migration thật, cố tình gắn sai dữ liệu và xác nhận database trả lỗi. Không dựa vào việc giao diện đã gửi đúng ID.

## 4. Tạo admin

`create-admin` nhận email/tên, hỏi mật khẩu ẩn hai lần. Service chuẩn hóa email, kiểm tra tên/mật khẩu, tạo băm scrypt bằng Werkzeug và ghi admin cùng audit trong một giao dịch.

Không có mật khẩu mặc định được ghi trong source. Nếu email đã thuộc admin đang hoạt động, lệnh không thay mật khẩu. Nếu email thuộc học viên hoặc tài khoản khóa, lệnh không tự đổi quyền. Web chưa có route đăng nhập; chưa có quyền đọc dữ liệu học viên được mở cho admin.

## 5. Nhập hai ca

1. Đọc JSON UTF-8, tối đa 1 MB/tệp; từ chối khóa JSON lặp và số NaN/Infinity.
2. Kiểm tra JSON Schema cục bộ: trường bắt buộc, loại, danh mục, số lượng dữ kiện/tiêu chí.
3. Kiểm tra mã trùng, tham chiếu, trọng số 30/20/20/20/10, trạng thái kết thúc và luật cùng ưu tiên bị chồng điều kiện.
4. Xác nhận email người nhập là admin ACTIVE.
5. Tìm mã ca và số phiên bản; cùng mã băm thì giữ nguyên, khác nội dung cùng phiên bản thì báo lỗi.
6. Tạo phiên bản DRAFT/demo, rubric và audit. Commit khi toàn bộ lô thành công; lỗi ở ca cuối rollback cả ca đã thêm trước đó.

Hash là SHA-256 của gói nhập được chuẩn hóa khóa/định dạng JSON, bao gồm hồ sơ rà soát lúc nhập. Nó nhận diện gói nhập; không phải chữ ký người thẩm định. Thay đổi khoảng trắng hoặc thứ tự thuộc tính JSON không tạo bản mới; thay đổi nội dung cần tăng `version_no`.

Gói nguồn có `rubric` để vận chuyển; khi nhập, rubric chuyển sang bảng `rubric_criteria`, không lưu thêm một bản trọng số trong `content_json`.

## 6. Các ràng buộc đã có

- Email duy nhất; vai trò và trạng thái trong danh mục.
- Khóa tạo lượt `(user_id, start_request_key)`, tin nhắn theo thứ tự và sự kiện theo khóa yêu cầu không trùng.
- Một phiên bản PUBLISHED cho mỗi ca; ca demo không thể PUBLISHED.
- Một operation RUNNING toàn dự án; lịch sử lần gọi API có khóa duy nhất theo operation/bước/lần thử.
- Tổng điểm chỉ tồn tại khi đánh giá VALID; điểm tiêu chí ACHIEVED/PARTIAL phải theo trọng số, không lấy tổng do AI tự đưa ra.
- Bản nộp chỉ thêm cho lượt COMPLETED và không sửa/xóa bằng thao tác dữ liệu thông thường; lượt đã đóng không mở lại bằng UPDATE.
- Danh tính chủ lượt, phiên bản và khóa tạo lượt bất biến.
- Nội dung/rubric của ca APPROVED/PUBLISHED/ARCHIVED không được sửa; không hạ ngược trạng thái về DRAFT để né ràng buộc.
- FK mặc định RESTRICT giữ lịch sử khi xóa tài khoản/ca đã được tham chiếu.

Các trigger có trong migration, không chỉ trong model. Khi thêm migration có rebuild bảng SQLite về sau, phải kiểm tra và tạo lại trigger liên quan. Không dùng `create_all` để thay migration trong test hoặc máy chạy.

## 7. Những kiểm tra còn thuộc các bước sau

Database chưa thay thế xác thực/kiểm tra quyền sở hữu ở route; bằng chứng cùng lượt chưa đủ chứng minh đoạn trích thật sự khớp hoặc hỗ trợ mức đạt. Dịch vụ Tutor sẽ kiểm tra đủ mọi tiêu chí, câu trích, tổng điểm và đóng giao dịch trước khi công bố VALID.

Đặt chỗ quota, kiểm soát chuyển trạng thái bằng `state_version`, lưu cặp hỏi/đáp nguyên tử, quản lý timeout và điều kiện phát hành sau rà soát sẽ triển khai cùng các service tương ứng. Chỉ mục RUNNING là nền khóa, chưa phải bộ điều phối AI đã hoạt động.

Các fixture trong gói JSON là đầu vào cho bước Scenario Engine. Chưa gọi AI, chưa đo 120 phản hồi Patient, 18 hội thoại hay 36 kết quả Tutor. Không dùng 43 test phần mềm để kết luận chất lượng AI/y khoa.

## Nguồn

- `flask_chapter7_Large Application Structure.html`: Factory, model, migration, cấu hình test.
- `flask_micro_project_tutorial.html`: ORM User, băm mật khẩu và quy trình Flask-Migrate.
- `MedQuest_AI_Use_Case_ERD_v1.docx`: 14 bảng P0 và khóa ghép.
- `MedQuest_AI_Thiet_ke_UI_Kien_truc_Flask_v1.docx`: thứ tự bước 2 và các cột chống trùng bổ sung.
- `MedQuest_AI_Dac_ta_chuc_nang_v2.docx`: MQ_COM_01, rubric và nhãn demo.
