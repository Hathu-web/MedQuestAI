# Bước 3 — Giải thích tài khoản và phân quyền

## 1. Luồng đăng ký

Trình duyệt gửi form có CSRF → `RegistrationForm` kiểm tra tên, email, độ dài/xác nhận mật khẩu → `register_student()` chuẩn hóa email và tạo User → băm mật khẩu bằng scrypt → lưu User cùng AuditLog trong một giao dịch → chuyển sang trang đăng nhập.

Server luôn đặt `role=STUDENT`, `status=ACTIVE`, `is_test_account=0`. Không lấy vai trò hoặc cờ kiểm thử từ form, nên sửa HTML hoặc gửi thêm trường `role=ADMIN` cũng không cấp quyền. Admin được tạo qua CLI như bước 2.

Email được chuẩn hóa Unicode, bỏ khoảng trắng hai đầu và chuyển chữ thường. Email đăng ký được kiểm tra cú pháp, không gọi DNS và chưa xác minh hộp thư. UNIQUE ở database chặn trùng kể cả khi hai yêu cầu cùng đến. Nếu ghi audit lỗi thì cả user mới cũng rollback.

## 2. Luồng đăng nhập

`LoginForm` kiểm tra đầu vào → `authenticate()` tìm email → kiểm tra băm mật khẩu → yêu cầu trạng thái ACTIVE → xóa dữ liệu phiên khách và gọi `login_user()` → chuyển về URL nội bộ hợp lệ hoặc `/account`.

Nếu email không tồn tại, service vẫn kiểm tra một băm giả để tránh bỏ qua chi phí kiểm tra mật khẩu. Email không tồn tại, sai mật khẩu và tài khoản bị khóa dùng cùng một thông báo; không có mật khẩu admin dùng chung trong source.

`safe_next_url()` không chỉ kiểm tra bắt đầu bằng `/`: còn từ chối `//`, dấu gạch chéo ngược, ký tự điều khiển và các dạng mã hóa lồng. URL quay lại chỉ dẫn tới trang nội bộ. Đăng xuất là POST có CSRF, không cho GET làm thay đổi phiên.

## 3. Vì sao thêm auth_version?

Cookie phiên Flask có chữ ký, không mã hóa. Flask-Login cần một định danh để nạp người dùng; ở đây định danh là `id:auth_version`, ví dụ `12:1`. Mỗi request được bảo vệ nạp lại tài khoản và kiểm tra ACTIVE cùng đúng phiên bản.

Khi đổi mật khẩu thành công, database tăng `auth_version` từ 1 lên 2. Cookie `12:1` ở các trình duyệt khác không còn dùng được. Trình duyệt vừa đổi mật khẩu được đăng nhập lại bằng `12:2`, nên tiếp tục sử dụng được.

Khóa hoặc mở khóa cũng tăng phiên bản. Vì vậy mở lại một tài khoản không làm sống lại cookie cũ. Đây là kiểm tra ở yêu cầu tiếp theo; không có WebSocket tự đóng tức thời trang đang mở và không thể thu hồi nội dung đã hiển thị trước đó.

Migration `0002_auth` chỉ thêm cột mặc định 1. Không xóa hoặc dựng lại bảng users, không thay đổi password_hash hay dữ liệu ca. Script sao lưu bằng SQLite backup API trước khi chạy migration; không sao chép thô một database có thể còn WAL.

## 4. Ba lớp kiểm tra quyền

| Kiểm tra | Câu hỏi | Cách dùng |
|---|---|---|
| Xác thực | Đang đăng nhập và tài khoản còn hiệu lực? | `login_required`, `user_loader` |
| Vai trò | Được dùng chức năng quản trị? | `admin_required` |
| Chủ sở hữu | Lượt này có thuộc chính người đang đăng nhập? | `get_owned_session()` lọc đồng thời ID và user_id |

Ẩn nút trên giao diện không thay thế kiểm tra server. Admin không có quyền đọc hội thoại học viên; một route/API mới về lượt thực hành cũng phải gọi hàm kiểm tra chủ sở hữu trước khi đọc/sửa dữ liệu.

HTML `/sessions/<id>` và JSON `/api/v1/sessions/<id>/state` hiện chỉ đọc dữ liệu đã có. Bước này chưa tạo lượt từ giao diện. Cả hai dùng cùng helper kiểm tra quyền, sau đó `public_session()` chọn rõ các trường được trả. Không dùng `model.__dict__` để gửi toàn bộ model.

`state_json`, dữ kiện chưa lộ, luật, rubric và payload nhà cung cấp AI không được trả qua API này. Tin nhắn trong HTML được Jinja escape; nếu có nội dung `<script>`, trình duyệt sẽ thấy văn bản, không thực thi nó.

## 5. Đổi mật khẩu và khóa tài khoản

Đổi mật khẩu cần mật khẩu hiện tại, mật khẩu mới đủ dài và khác mật khẩu cũ. UPDATE kiểm tra lại trạng thái, phiên bản và băm cũ; nếu tài khoản vừa đổi ở nơi khác thì từ chối thay vì ghi đè. Đổi mật khẩu và audit cùng giao dịch.

Trang admin chỉ cho khóa/mở STUDENT, không sửa quyền, không xem/sửa mật khẩu, không tự khóa admin. GET chỉ hiển thị trang xác nhận. POST có CSRF mang trạng thái người quản trị đã nhìn thấy; nếu trạng thái đã thay đổi thì báo 409 và yêu cầu tải lại. Audit chỉ lưu trạng thái trước/sau, không chứa mật khẩu.

Giới hạn tần suất tại local: đăng nhập 10 lần/phút/IP; đăng ký và đổi mật khẩu mỗi loại 5 lần/phút/IP. Tính cả lần thành công và sai sau khi qua CSRF. Dùng `remote_addr`, không tin `X-Forwarded-For` gửi tùy ý. Bộ đếm có khóa thread và giới hạn số khóa trong RAM; nhiều tiến trình cần giải pháp dùng chung ở giai đoạn triển khai.

## 6. Tự kiểm tra để báo cáo

- Tạo học viên rồi đăng nhập: thấy tên/email, không có liên kết Quản trị.
- Đổi mật khẩu: mật khẩu cũ thất bại, mật khẩu mới thành công; trình duyệt thứ hai phải đăng nhập lại.
- Admin khóa học viên: học viên bị từ chối ở request tiếp theo; mở khóa không khôi phục cookie cũ.
- Đổi ID lượt trong URL/API: không xem được lượt người khác, kể cả khi dùng admin.
- Nâng cấp database bước 2: có bản sao revision cũ; admin/mật khẩu/hai ca giữ nguyên; revision mới là `0002_auth`.

Bộ unittest dùng SQLite tạm riêng và Flask test client để mô phỏng các tình huống trên. Không dùng database đang chạy của bạn. Hai tệp kiểm thử mới còn kiểm tra chống CSRF, chuyển hướng bên ngoài, ghi giao dịch nguyên tử và lỗi database chưa nâng cấp.

## 7. Phần sẽ làm sau

Bước 4 mở thư viện ca và tạo/tiếp tục lượt. Các ca hiện vẫn là bản nháp demo kỹ thuật; chưa tự phát hành thành ca đào tạo được duyệt. Bước 5 nối Scenario Engine/FakeAI, rồi mới thêm AI Patient, Tutor và giới hạn chi phí. Quên mật khẩu qua email và sửa hồ sơ không nằm trong bước 3.
