# Tài nguyên giao diện

- `app/static/images/patient-room.png`: ảnh bệnh nhân giả lập 2D tạo bằng công cụ ImageGen tích hợp từ bản phác thảo đã chốt; là tài nguyên hiển thị, không có bệnh án hoặc dữ liệu y khoa thật. Ảnh được đưa vào dự án để dùng offline.
- Logo chữ và favicon SVG: thành phần đồ họa đơn giản trong mã nguồn.
- Bootstrap CSS **5.3.8**, giấy phép MIT: `app/static/vendor/bootstrap/LICENSE`.
- Bootstrap Icons **1.13.1**, giấy phép MIT: `app/static/vendor/icons/LICENSE`.
- Font hệ thống Segoe UI/Arial, không tải font ngoài.

Nguồn tài nguyên vendor: `https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/` và `https://cdn.jsdelivr.net/npm/bootstrap-icons@1.13.1/`. Khi chạy, trình duyệt chỉ yêu cầu tệp local.

## Prompt tạo ảnh bệnh nhân

Use case: precise-object-edit. The attached image is an approved MedQuest AI application mockup. Extract and expand ONLY its central illustrated patient-in-hospital scene into a clean, standalone wide landscape bitmap asset for the actual Flask application's patient panel. Preserve the same Vietnamese middle-aged male character, facial features, worried but alert expression, light blue gown, hands resting on the white blanket, semi-upright bed posture, warm overhead bedside light, and navy/pale-blue hospital illustration style. Fill the entire new 16:9 composition with the hospital scene. Patient centered and shown waist-up with bed foreground; leave modest room context around his shoulders. Remove absolutely ALL text, numbers, logos, badges, chat bubbles, buttons, side panels, tutor avatar, UI borders, overlays, charts, and screens from the supplied mockup. Equipment can remain as quiet unlabelled background shapes; no ECG traces or measured vital signs. No oxygen mask, no medical advice, no extra people. Crisp polished semi-realistic 2D illustration, restrained blue palette with natural warm skin tones. This is a project asset, not an entire interface.

## Ảnh bổ sung bước 2 (26/10/2026)

- `app/static/images/patient-female.png`: nhân vật nữ giả lập Trần Ngọc Linh, 28 tuổi; dùng ngay trong UI preview và tham chiếu bởi `female_adult` trong MQ_COM_02.
- `app/static/images/patient-student.png`: An, nam 22 tuổi, khớp ca MQ_COM_01 trong đặc tả; dành cho luồng chọn ca sau này.
- Giữ `patient-room.png` của bước 1 cho nhân vật nam 45 tuổi trong UI preview.
- Cả hai ảnh mới: PNG 1672 × 941, tạo bằng ImageGen tích hợp (built-in), dùng ảnh nam ban đầu làm edit target để giữ nhất quán ánh sáng/bối cảnh/phong cách. Không dùng CLI hoặc API key của người học.

### Prompt ảnh nữ

Use case: precise-object-edit. Asset type: second fictional patient illustration for MedQuest AI, an educational Vietnamese patient interview simulator. Edit target: the provided image. Create a female counterpart by changing only the patient to a fictional Vietnamese adult woman, approximately 28 years old, natural dark shoulder-length hair tucked behind ears, ordinary natural face with a slightly concerned but alert and approachable expression. She is seated upright in the same hospital bed, wearing the same modest light blue patient gown, hands relaxed together over blanket, looking toward viewer ready to speak. Preserve the original polished semi-realistic 2D digital illustration style, exact landscape composition and framing, navy and teal cool hospital palette, soft warm headboard light, bedding, furniture, props, perspective and background. This is a companion asset, not a UI screenshot. No oxygen mask or breathing tubes, no dramatic distress, no medical treatment, no text, labels, watermark, or interface. Keep her head and hands comfortably inside frame. Wide 16:9 image.

### Prompt ảnh nam 22 tuổi

Use case: precise-object-edit. Asset type: MedQuest AI Vietnamese educational patient conversation illustration. Edit target: provided image. Change ONLY the male patient to a fictional Vietnamese male university student, 22 years old, natural short black hair, fresh young adult face without middle-aged wrinkles, concerned but alert and comfortable enough to talk. Preserve original hospital bed, posture, hands resting together on blanket, modest blue patient gown, no mask or tubes, wide 16:9 framing, navy teal hospital room, warm overhead lamp, bedding, equipment, background, perspective. Match the polished semi-realistic 2D digital illustration exactly. No text, watermark, interface, diagnoses, treatment or dramatic distress. This illustration is for the approved case An, age 22, a student worried about fatigue before exams.

## Bộ chân dung ngoại trú mới — bản bàn giao 04/11/2026

Ảnh được tạo bằng công cụ ImageGen tích hợp, không dùng CLI/key của người học. Đây là các nhân vật hư cấu, không phải ảnh người bệnh thật. Giữ ảnh cũ để các phiên bản cũ vẫn có thể đọc lại; bộ ca mới dùng bốn tệp riêng:

| Nhân vật | Tệp trong source | Kích thước |
|---|---|---|
| An, nam 22 tuổi | `app/static/images/patient-an.png` | 1672 × 941 |
| Linh, nữ 28 tuổi | `app/static/images/patient-linh.png` | 1672 × 941 |
| Minh, nam 45 tuổi | `app/static/images/patient-minh.png` | 1672 × 941 |
| Hương, nữ 40 tuổi | `app/static/images/patient-huong.png` | 1672 × 941 |

### Prompt An

Use case: illustration-story. Create wide landscape 16:9 semi-realistic polished digital illustration for a medical training website. Wholly fictional Vietnamese male university student aged 22, short black hair and youthful natural face, wearing simple light blue casual shirt with rolled sleeves and navy trousers. He sits in a comfortable outpatient consulting room chair, hands relaxed on thighs, mild tired worried expression, directly facing camera as student interviewer. Waist-up to knees framing, face central in upper third. Contemporary Vietnamese clinic, pale blue curtains, navy upholstered furniture, soft daylight, discreet shelves and medical instruments in soft focus. Calm, respectful, anatomically plausible natural skin texture and fabric, not cartoon or anime. No hospital bed or gown, blankets, IV, tubes, text, logos, other people or watermark. Opaque background.

### Prompt Linh

Use case: illustration-story. Create wide landscape 16:9 semi-realistic polished digital illustration for a medical training website. Wholly fictional Vietnamese woman aged 28, shoulder-length straight black hair, youthful natural oval face, wearing a modest soft dusty blue casual blouse and navy trousers. She sits in an outpatient consulting room chair, hands loosely together in lap, a slightly reserved but receptive expression, facing the student interviewer/camera. Waist-up to knees framing with face central in upper third. Contemporary private Vietnamese clinic, a closed blue privacy curtain, navy furniture, soft daylight, subtle plant and ordinary examination instruments in soft focus. Calm, respectful, anatomically plausible natural skin and fabric, not anime or cartoon. No hospital bed or gown, blankets, IV, tubes, text, logos, other people, watermark. Opaque background.

### Prompt Minh

Use case: illustration-story. Asset type: MedQuest AI virtual patient website cover, wide landscape 16:9. Create one polished semi-realistic digital illustration of a wholly fictional Vietnamese man aged 45, short slightly greying black hair, broad natural face, average build, wearing a muted blue casual polo and dark trousers. He sits upright carefully on the edge of an outpatient examination couch, hands resting on thighs, mild worried expression, looking toward the student interviewer/camera. This is a back pain history interview, not an emergency. Modern small Vietnamese outpatient consulting room, navy and soft blue furnishings, daylight, pale blue privacy curtain, discreet examination equipment in soft focus. Waist-up to knees framing with face central in upper third for card cropping. Respectful, anatomically plausible, calm, visually matches refined blue medical training illustrations. No bed blankets, IVs, masks, tubes, text, labels, logos, watermark, other people. Opaque background.

### Prompt Hương

Use case: illustration-story. Asset type: MedQuest AI virtual patient website cover, wide landscape 16:9. Create one polished semi-realistic digital illustration of a wholly fictional Vietnamese woman aged 40, shoulder-length softly wavy dark hair tied half back, oval natural face, medium build, wearing a teal modest casual blouse and dark trousers. She sits in a comfortable outpatient consultation chair with hands resting loosely in lap, thoughtful slightly concerned expression, looking toward student interviewer/camera. This is a history interview about burning upper abdomen after meals, not an emergency. Modern small Vietnamese outpatient consulting room with navy and soft blue palette, warm daylight, pale blue privacy curtain, subtle shelf and plant, medical equipment in soft focus. Waist-up to knees framing with face central in upper third for card cropping. Respectful, anatomically plausible, calm refined blue medical training illustration. No hospital bed, blankets, IVs, tubes, masks, text, labels, logos, watermark, other people. Opaque background.
