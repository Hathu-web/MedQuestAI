# Kết quả kiểm tra bộ bốn ca

Bản bàn giao: `08-four-patient-curriculum`, hoàn thiện ngày 04/11/2026.

## Đã kiểm tra trên bản tham chiếu

| Hạng mục | Kết quả |
|---|---|
| Toàn bộ unittest | 236 test, 58.085 giây, OK trên Linux/Python 3.12 |
| Phần mới | 18 test về bộ ca, index, phát hành, backup, chạy lại, quyền và bảo toàn lịch sử |
| Retrieval của bốn ca | 40 câu tác giả soạn tìm được nguồn kỳ vọng với embedding kiểm thử; đây không phải benchmark model thật |
| Dữ liệu | 4 ca riêng, 2 nam/2 nữ; 146 dữ kiện; 9 tiêu chí mỗi ca, tổng 100, phân bổ 30/20/20/20/10 |
| Phát hành | Thiếu index của một ca thì rollback toàn bộ giao dịch phát hành |
| Mất mạng | Nhập DRAFT rồi index lỗi; chạy lại cùng lệnh tiếp tục thành công, không nhân đôi ca |
| Sao lưu | Tệp backup giữ đúng tài khoản và trạng thái DB trước cập nhật; không ghi đè backup đã có |
| Dữ liệu cũ | Giữ version/hash, phiên thực hành và tin nhắn cũ sau lưu trữ ca; vẫn truy cập lịch sử bằng quyền sở hữu |
| Thư viện | HTTP test render đúng 4 thẻ, không lộ facts/rubric ẩn; học viên thấy nút Bắt đầu thực hành |
| Giới hạn AI | Tắt Patient/Tutor hoặc dùng demo/local thì từ chối mở ca học phần, không tiêu lượt mới |
| Phát hành lại | Không tạo audit trùng; chỉ mục hợp lệ được dùng lại, không gọi embedding lần nữa |
| Xung đột dữ liệu | Từ chối ghi đè cùng số phiên bản có nội dung khác hoặc quay lùi phiên bản mới hơn |
| Phân quyền | Admin thực hiện phát hành; học viên không thể dùng lệnh service để tự phát hành |
| Tính trung thực của review | Không tự ghi PASSED hoặc người duyệt chuyên môn; release ghi COURSEWORK, clinical_approval=false |
| Phụ thuộc | `pip check`: No broken requirements found |
| WinError32 | Giữ bản sửa đóng connection/engine trong preflight và fixture kiểm thử của bản trước |
| Ảnh | 4 ảnh riêng được tạo và kiểm tra trực quan, đưa vào static và tham chiếu đúng nhân vật |

File log đầy đủ trong gói bàn giao là `KET_QUA_TEST.txt`. Các test dùng DB tạm và provider thay thế, không đọc `.env`/API key/DB người dùng. Kết quả 236 test bao gồm các test Tutor, bảo mật, migration, RAG và Docker preflight đã có.

## Giới hạn của kết quả

- Chưa chạy bộ ca mới bằng API key/model thật của bạn hoặc trên máy Windows của bạn. Lệnh `catalog install` sẽ gọi embedding trên máy bạn; chất lượng Patient/Tutor cần kiểm tra theo danh sách nghiệm thu trong FOUR_CASES.md.
- Chưa có giảng viên chấm độc lập bộ hội thoại để đo độ đồng thuận với Tutor. Kiểm tra đúng JSON, điểm và nguồn không chứng minh mọi diễn giải của LLM đều đúng.
- Không có trình duyệt Chromium cài trong môi trường này. Đã kiểm tra HTML bằng Flask test client; chưa kiểm tra trực quan cả trang desktop/mobile bằng browser. Bố cục Bootstrap đặt hai cột từ kích thước md và một cột trên màn hình nhỏ.
- Không có Docker Engine; chưa build/chạy image hoặc workflow GitHub. Các file Docker được giữ để bạn dùng trên máy/runner phù hợp.
- Không có thao tác push GitHub, deploy hoặc sửa database đang dùng trên Windows. Bạn cần chép gói và chạy lệnh cài bộ ca.

Revision database vẫn `0003_rag`: 15 bảng nghiệp vụ/chỉ mục và `alembic_version`. Bộ ca mới dùng các bảng đã có. Không cần tạo migration mới, downgrade hoặc tạo lại database.
