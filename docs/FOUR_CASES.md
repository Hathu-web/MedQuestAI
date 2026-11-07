# Bộ bốn ca học phần — 30/10/2026

## Nội dung và phiên bản

| Mã | Phiên bản mới | Nhân vật | Số dữ kiện | Rubric |
|---|---:|---|---:|---:|
| MQ_COM_01 | 4 | Nguyễn Văn An, nam 22 tuổi, mệt và khó tập trung | 37 | 9 tiêu chí / 100 điểm |
| MQ_COM_02 | 2 | Trần Ngọc Linh, nữ 28 tuổi, tiểu buốt | 35 | 9 tiêu chí / 100 điểm |
| MQ_COM_03 | 1 | Lê Quốc Minh, nam 45 tuổi, đau lưng sau nâng hàng | 36 | 9 tiêu chí / 100 điểm |
| MQ_COM_04 | 1 | Phạm Thu Hương, nữ 40 tuổi, nóng rát vùng bụng trên sau ăn | 38 | 9 tiêu chí / 100 điểm |

Mỗi nhân vật có chân dung ngoại trú riêng, lời mở đầu, công việc, cách xưng hô, nỗi lo, kỳ vọng, bệnh sử hiện tại, tiền sử, thuốc/dị ứng, dữ kiện phủ định và những điều chưa rõ. Không chỉ đổi tên hoặc giới tính trên một mẫu bệnh án.

Kịch bản mới tách khỏi các phiên bản trước. Linh v2 là tình huống tiết niệu khác Linh v1; các lượt v1 vẫn dùng bệnh sử cũ. Không trộn nội dung hai phiên bản vào một lần học.

## Đổi từ ca kiểm thử sang ca học phần

`python -m flask --app medquest catalog install --admin-email admin@medquest.local`

1. Kiểm tra đúng schema, admin đang hoạt động, bốn JSON và cấu hình AI thật.
2. Từ chối nếu database đã có bản cùng số nhưng nội dung khác hoặc có phiên bản mới hơn. Không ghi đè công việc của người dùng.
3. Sao lưu SQLite bằng backup API vào thư mục `backups` cạnh database đang dùng. Đường dẫn nguồn/bản sao được in ra, không in API key.
4. Nhập bốn bản DRAFT nếu chưa có. Nhập lại cùng dữ liệu không tạo bản trùng.
5. Đọc ca từ database, tạo embedding cho đoạn dữ liệu, lưu vào `ai_chunks`. Chỉ mục còn hợp lệ được giữ.
6. Chỉ sau khi cả bốn chỉ mục hợp lệ, một giao dịch đổi các bản cũ cùng mã sang ARCHIVED và bốn bản mới sang PUBLISHED. Không xóa dữ liệu cũ.
7. Lưu audit và phạm vi phát hành COURSEWORK với admin thực hiện. Không giả mạo tên người thẩm định hoặc đổi `review.medical/training` thành PASSED.

PUBLISHED ở đây là trạng thái khả dụng của nội dung trong app, không phải xác nhận chất lượng lâm sàng. Màn hình duyệt chuyên môn nhiều người và sửa điểm giảng viên chưa được triển khai.

Nếu mất mạng giữa bước 5, các ca mới vẫn là DRAFT. Các bản đã phát hành trước đó giữ nguyên. Chạy lại lệnh sau khi hết lỗi để tiếp tục. Không chạy setup_database, downgrade hoặc xóa database để sửa lỗi index.

## Hội thoại và rubric

- Câu hỏi sinh viên + lịch sử gần đây → embedding → tìm dữ kiện **cùng phiên bản ca**, lọc quyền tiết lộ → LLM đóng vai bệnh nhân → kiểm tra cấu trúc/nguồn → lưu tin nhắn và nguồn.
- RAG vẫn lấy dữ liệu đã lưu trong database. JSON là gói nhập, không được đọc thay database mỗi lần chat.
- Không yêu cầu đúng từ khóa hoặc câu mẫu. Nguồn phù hợp được truy xuất theo nghĩa và từ vựng. Ví dụ sinh viên có thể hỏi “em mệt kiểu gì”, “cảm giác uể oải ra sao” hoặc hỏi tiếp điều vừa nghe.
- Có lời chào, đồng cảm, hỏi lại và chuyển hướng khi ngoài vai. Nội dung thiếu dữ kiện được báo riêng, không bịa thành kết quả âm tính hoặc bệnh nhân không nhớ.
- `KNOWN`, `ABSENT`, `UNKNOWN`, `UNSPECIFIED` giữ các ý nghĩa khác nhau. Ví dụ chưa thử thai không có nghĩa là không mang thai; chưa đo nhiệt độ không tạo ra số đo bình thường.
- Câu hỏi riêng tư có điều kiện chia sẻ. Xin phép/đồng cảm giúp bệnh nhân hợp tác; gây áp lực có thể khiến bệnh nhân dè dặt. Triệu chứng cảnh báo không bị khóa sau nhánh nỗi lo riêng.
- Các ca mới không có nút gửi lời đáp soạn sẵn. Sinh viên tự giới thiệu, xin phép, đồng cảm và tóm tắt trong hội thoại.

Rubric từng ca có 3 tiêu chí về vấn đề hiện tại (30), 2 tiêu chí liên quan (20), 2 tiêu chí giao tiếp (20), 1 tiêu chí nhận định giới hạn/bước tiếp theo (20) và 1 tiêu chí tóm tắt/xác nhận (10). Nội dung tiêu chí triệu chứng thay đổi theo từng ca.

Hỏi tính chất mệt được tính ở tiêu chí riêng. Hỏi một triệu chứng đi kèm như đau đầu được ghi nhận một phần ở nhóm sàng lọc; không bị bỏ qua vì rubric chỉ có giấc ngủ hoặc kỳ thi. Tutor vẫn cần dẫn chứng nguyên văn câu học viên. Câu bệnh nhân tự kể không tự chứng minh học viên đã khai thác đầy đủ; một câu hỏi mở tốt có thể là bằng chứng phù hợp.

Không chấm lại các lượt cũ bằng rubric mới. Tổng điểm được code tính từ mức đạt và trọng số, không nhận tổng do LLM tự khai.

## Nguồn tham khảo và phần tự soạn

Đã đối chiếu các trang NHS ngày 30/10/2026:

- [Tiredness and fatigue](https://www.nhs.uk/conditions/tiredness-and-fatigue/): tham khảo các nhóm khai thác về ngủ, sinh hoạt, tác động và triệu chứng đi kèm; không dùng để kết luận nguyên nhân mệt của An.
- [Urinary tract infections](https://www.nhs.uk/conditions/urinary-tract-infections-utis/): tham khảo nhóm triệu chứng đường tiểu, sốt, hông lưng và các yếu tố cần đánh giá thêm.
- [Back pain](https://www.nhs.uk/conditions/back-pain/): tham khảo các câu hỏi về vận động, thần kinh, đại tiểu tiện, chấn thương và triệu chứng toàn thân.
- [Heartburn and acid reflux](https://www.nhs.uk/conditions/heartburn-and-acid-reflux/): tham khảo biểu hiện nóng rát, vị chua, liên quan ăn/tư thế và triệu chứng cần khám thêm. Không coi mọi khó chịu ngực là trào ngược.

Tên, tuổi, nghề, số ngày, mức độ, tiền sử, câu trả lời, tình huống giao tiếp và rubric đều được AI hỗ trợ **tự soạn hư cấu**. Không phải ca thật, không trích nguyên bệnh án, không phải nội dung lâm sàng do cô đã phê duyệt. Không chứa đơn thuốc hoặc hướng dẫn điều trị. Nguồn tham khảo không tự biến toàn bộ kịch bản thành guideline.

## Nghiệm thu trên máy bạn

Sau khi cài bộ ca và chạy Flask:

1. Đăng nhập học viên, mở `/cases`: có 4 nhân vật, 2 nam/2 nữ, không có ba thẻ An v1/v2/v3. Màn hình hai cột trên desktop, một cột trên điện thoại.
2. Mở An: giới thiệu/xin phép → hỏi “em mệt kiểu gì” → “có đau đầu không” → “ngủ được mấy tiếng”. Nguồn phải thuộc An v4 và phản hồi theo từng câu; không xuất hiện bệnh sử tiểu buốt của Linh.
3. Mở Linh: hỏi tiểu rát và sốt/hông lưng; xin phép trước câu hỏi riêng tư. Khi hỏi chắc chắn không mang thai hay chưa, không được tự khẳng định không có thai.
4. Mở Minh: hỏi đau có lan/yếu chân và thay đổi đại tiểu tiện. Không tự có kết quả MRI hoặc chẩn đoán thoát vị.
5. Mở Hương: hỏi bữa ăn, tư thế, nuốt nghẹn, phân đen và khó chịu khi gắng sức. Không tự kết luận tất cả là bệnh dạ dày.
6. Tóm tắt trong hội thoại, xin người bệnh xác nhận; sau đó nộp bản tổng kết. Mở từng tiêu chí Tutor để so dẫn chứng với câu đã gửi. Tổng điểm bằng tổng điểm tiêu chí; không đòi bài nào cũng đạt điểm cao.
7. Tải lại trang: tin nhắn/điểm giữ nguyên. Đăng xuất và đăng nhập lại: đọc được lịch sử của mình. Tài khoản khác không đọc được lượt này.
8. Đọc lại một lượt cũ: vẫn giữ bệnh sử, tin nhắn và điểm trước cập nhật.

Mặc định tối đa 3 lượt mới/ngày/tài khoản; có thể thử 3 ca rồi ca còn lại vào hôm sau hoặc dùng tài khoản học viên thứ hai để kiểm thử. Không xóa lịch sử để vượt hạn mức. Admin kiểm tra cùng AI nhưng lượt TEST không tính thống kê học viên. API lỗi cần xử lý thông báo; không xem thông báo lỗi là câu trả lời bệnh nhân.

Bộ test tự động dùng provider thay thế, không chứng minh LLM thật trả đúng mọi câu hoặc các ca đã được thẩm định chuyên môn. Kiểm tra bằng model đang chạy của bạn là bước nghiệm thu cuối trên máy Windows.
