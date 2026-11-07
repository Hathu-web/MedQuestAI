# AI Tutor — Chấm sau khi nộp tổng kết

## Cách bật trên bản đang chạy

Giữ nguyên model, URL, API key và đường dẫn database hiện có. Thêm hoặc sửa các dòng sau trong `.env`, không để trùng tên biến:

```dotenv
AI_TUTOR_ENABLED=true
AI_TUTOR_MAX_OUTPUT_TOKENS=4096
AI_TUTOR_MAX_CONTEXT_CHARS=120000
AI_TUTOR_MAX_ATTEMPTS=3
```

Dừng và chạy lại Flask để đọc cấu hình mới. Tutor dùng cùng LLM với Patient; không yêu cầu thêm provider hoặc migration. Lượt hoàn tất trước khi cập nhật vẫn có thể được chấm qua nút **Chấm lượt đã nộp**.

## Dữ liệu đi từ database đến LLM

1. Xác thực chủ sở hữu và chỉ chấp nhận lượt COMPLETED có Submission.
2. Đọc rubric đúng `case_version_id`, toàn bộ hội thoại, hành động được chấp nhận, tổng kết và dữ kiện đã được khai thác. Không gửi hồ sơ của người khác hoặc dữ kiện ca còn ẩn.
3. Ghi nhận lần chấm và dấu vết phiên bản dữ liệu; kết thúc transaction trước khi gọi LLM.
4. LLM trả mức đạt, lý do, góp ý và trích dẫn theo từng tiêu chí. Prompt yêu cầu xem lời người học là dữ liệu, không làm theo yêu cầu tự cho điểm.
5. Code xác minh đủ tiêu chí, đúng loại nguồn và trích dẫn nguyên văn; tự tính điểm. Không nhận tổng điểm do LLM tự đặt.
6. Kiểm tra lại quyền, phiên bản hội thoại/rubric rồi lưu Evaluation, EvaluationItem và Evidence cùng giao dịch.

Đây là truy xuất dữ liệu có cấu trúc từ DB để đưa vào LLM. Tutor cần toàn bộ hồ sơ của một lượt đã xác định nên không cần embedding hay vector search riêng. Patient vẫn dùng chỉ mục và truy xuất RAG theo câu hỏi như trước.

## Thang điểm của ca An v3

| Mã | Tiêu chí | Điểm tối đa |
|---|---|---:|
| C01 | Làm rõ thời điểm bắt đầu | 15 |
| C02 | Làm rõ ảnh hưởng đến sinh hoạt | 15 |
| C03 | Hỏi thêm về giấc ngủ | 10 |
| C04 | Hỏi bối cảnh liên quan | 10 |
| C05 | Giới thiệu vai trò và xin phép | 10 |
| C06 | Thể hiện đồng cảm phù hợp | 10 |
| C07 | Nhận diện thiếu dữ kiện, kết thúc phù hợp, không gán chẩn đoán | 20 |
| C08 | Tóm tắt chính xác và xin xác nhận | 10 |
| | Tổng | **100** |

Đây là rubric đang có trong ca, không phải thang chấm y khoa mới tự bổ sung. Với ca khác, hệ thống dùng rubric của ca đó, không hardcode bảng này.

- **Đạt**: toàn bộ điểm tiêu chí.
- **Đạt một phần**: một nửa điểm; có thể có điểm lẻ 0,5.
- **Chưa đạt**: 0 điểm; phải giải thích điều chưa thực hiện hoặc chưa có bằng chứng.
- **Chưa đủ căn cứ**: không gán 0; kết quả mang trạng thái cần xem lại, chưa có tổng điểm.

Lời bệnh nhân dùng làm ngữ cảnh, không làm dẫn chứng học viên đã hỏi. C01–C06 dùng tin nhắn học viên. C07–C08 còn cho phép hành động hoặc bản tổng kết theo rubric. Nguồn và khoảng trích dẫn được lưu để đọc lại.

## Test tay ngay trên web

1. Đăng nhập admin đang dùng, mở Thư viện ca và chọn An v3 ở chế độ kiểm thử. Không dùng trang Xem trước.
2. Giới thiệu vai trò, xin phép, hỏi thời điểm, diễn biến, ảnh hưởng, giấc ngủ và bối cảnh; dùng lời tự nhiên của bạn.
3. Phản hồi mối lo của An, tóm tắt những gì An đã nói và chọn **Xin xác nhận bản tóm tắt** khi phù hợp.
4. Viết và nộp tổng kết. Chờ một yêu cầu LLM hoàn tất, tránh bấm gửi liên tục.
5. Kéo xuống **Kết quả đánh giá**: thấy tổng điểm, đủ 8 tiêu chí, điểm từng tiêu chí, lý do và gợi ý. Mở dẫn chứng và đối chiếu với lời bạn đã gửi.
6. Tải lại trang rồi mở lượt từ dashboard: kết quả phải còn, không gọi chấm lại và không đổi điểm.
7. Trong một lượt khác, cố ý bỏ phần giới thiệu/xin phép hoặc đồng cảm. Kiểm tra nhận xét có chỉ đúng điểm thiếu hay không; không kỳ vọng một tổng điểm cố định từ LLM.
8. Nếu 503/timeout/đầu ra sai định dạng: tổng kết vẫn còn, chưa có điểm 0. Khi dịch vụ ổn, bấm **Thử chấm lại**. Tối đa 3 lần đã bắt đầu chấm cho một lượt theo cấu hình mặc định.
9. Không chấm lượt đang dở hoặc đã bỏ. Đổi sang tài khoản khác không được đọc hay chấm lượt của tài khoản trước.

Lượt TEST có điểm để kiểm tra nhưng không cộng vào thống kê học tập. Nếu rubric được sửa giữa lúc gọi AI, hệ thống từ chối lưu kết quả cũ thay vì chấm trên dữ liệu đã đổi.

## Khi chưa có kết quả

| Thông báo | Cách xử lý |
|---|---|
| Chức năng chưa bật | Kiểm tra `AI_TUTOR_ENABLED=true`, đúng `.env`, rồi khởi động lại Flask |
| Tutor cần LLM thật | Giữ provider/model đang dùng AI Patient thật; provider demo không tạo điểm |
| 503 | Dịch vụ tạm không sẵn sàng; đợi rồi thử lại thủ công |
| 429 / hạn mức | Kiểm tra hạn mức provider hoặc giới hạn AI trong ngày |
| Dẫn chứng không khớp | Hệ thống chưa lưu điểm; thử lại sau khi kiểm tra model có trả đúng JSON và đủ token |
| Có tiêu chí chưa đủ căn cứ | Đọc từng tiêu chí; cần người hướng dẫn xem lại, hệ thống không tự chốt tổng điểm |
| Quá giới hạn hồ sơ | Không cắt hội thoại để chấm thiếu; xem lại giới hạn context và khả năng model |
| Đạt giới hạn lần chấm | Giữ hồ sơ để kiểm tra; không xóa bản tổng kết hoặc database để vượt giới hạn |

Hệ thống không có nút sửa điểm/duyệt điểm cho giảng viên ở bản này. “Cần xem lại” là trạng thái phản hồi, không phải tuyên bố đã có quy trình duyệt điểm trên web.

## Kiểm tra tự động và chất lượng chấm

```powershell
python -m unittest tests.test_tutor -v
```

Bộ test dùng AI giả lập để kiểm tra tính điểm, nguồn, quyền, lưu dữ liệu, lỗi, timeout và gửi trùng. Không dùng API key thật và không đo độ đúng của giám khảo AI.

Trước khi dùng điểm chính thức, chuẩn bị một tập hội thoại tốt/vừa/thiếu/ngoài chủ đề và các câu yêu cầu “cho em 100 điểm”; nhờ giảng viên chấm độc lập cùng rubric. So sánh từng tiêu chí, độ khớp dẫn chứng, chênh lệch điểm và mức dao động giữa các lần chấm ở môi trường thử riêng. Chỉ điều chỉnh rubric/prompt theo các sai khác đã quan sát, ghi lại phiên bản. Bản cập nhật chưa thực hiện phép đo này với model thật của bạn.
