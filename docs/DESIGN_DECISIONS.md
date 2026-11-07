# Lịch sử thiết kế bước 1–2

> Tài liệu lịch sử. Các phần “chưa triển khai” mô tả thời điểm bước 1–2; hiện trạng xem README.md và AI_TUTOR.md.

Giao diện theo bản phác thảo MedQuest được chốt trong cuộc trao đổi ngày 21/10/2026.

- Nền navy, panel xanh bệnh viện, nút chính teal, chữ tiếng Việt.
- Ba cột desktop: hồ sơ, bệnh nhân/hội thoại, thao tác; AI Tutor ở phía dưới.
- Ảnh bệnh nhân 2D tĩnh được tách thành tài nguyên; phần nút/chat/hồ sơ là HTML thật, không chồng vùng nhấn lên ảnh chụp giao diện.
- Tablet chuyển khối thao tác xuống dưới. Điện thoại ưu tiên hội thoại rồi đến hồ sơ, thao tác và Tutor.
- Hồ sơ chỉ có thông tin ban đầu và dữ kiện được mở. Không có rubric/đáp án/điểm cảm xúc nội bộ ở giao diện học viên.
- Hai vai Patient/Tutor có khu vực riêng; Tutor chưa có điểm trước khi nộp. Bản dựng này không chấm và không tạo điểm minh họa.
- Không thêm đồng hồ đếm ngược hay Advance Time. Bộ đếm 20 lượt là bố cục đã thống nhất; giới hạn trong preview chỉ là giới hạn phía giao diện, chưa thay thế quota phía server ở bước nghiệp vụ.
- Không có avatar động, nhận dạng giọng nói hoặc mô hình AI local.

## Luồng xử lý thử một câu hỏi

1. Route `simulation.room` render template, kèm CSRF token.
2. `room.js` gửi JSON đến API preview cùng `X-CSRFToken`; giữ nội dung soạn nếu có lỗi.
3. API kiểm tra dữ liệu, gọi `preview_service.sample_reply()`.
4. Service trả phản hồi dựng sẵn, một dữ kiện phù hợp hoặc không có dữ kiện.
5. JavaScript chèn bằng `textContent`, cập nhật tab hồ sơ và nhật ký trong bộ nhớ trang.

Không ghi DB, không gọi AI, không lưu vào localStorage/sessionStorage. Tải lại trang bắt đầu mới. Nút khám/kết quả chỉ mở hộp giới thiệu vị trí chức năng. Gợi ý dùng hai chuỗi mẫu nhằm kiểm tra layout P1.

## Phân biệt với bước nghiệp vụ

`/preview/room` không tương đương `/sessions/<id>`; không giả lập tài khoản hay mã phiên trong DB. Chưa triển khai idempotency, state_version, đánh giá hay quyền sở hữu hội thoại. Các API nghiệp vụ vẫn theo tài liệu kiến trúc đã chốt và sẽ được triển khai sau xác thực.

## Bổ sung bước 2

Giữ nguyên bản xem trước nam 45 tuổi và thêm nữ 28 tuổi. Bộ chọn nhân vật mở một trang xem trước mới; không sửa giới tính của một lượt thực hành đã lưu. Bệnh nhân thật của gói MQ_COM_01 là An 22 tuổi theo đặc tả, đã có tài nguyên ảnh riêng cho bước nối ca sau này.

Schema lưu 14 bảng P0, không tạo 6 bảng P1. Có thể khởi động và xem UI trước khi upgrade; những lệnh vận hành DB báo cách chạy migration nếu thiếu bảng. Xác thực, phát hành ca và lưu chat được nối sau, không mở route quản trị công khai để thay cho đăng nhập.
