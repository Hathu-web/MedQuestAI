> Cập nhật bộ ca 30/10/2026: dùng `catalog install --admin-email <email-admin>` sau khi cấu hình AI thật để nhập/index/phát hành bốn ca. `import-cases` chỉ nhập DRAFT. Giữ database đã cập nhật trong volume; không cần migration mới hoặc Docker Desktop trên máy đang chạy Flask.

# Chuẩn bị Docker — không cần Docker Desktop trên máy hiện tại

Bạn vẫn chạy và thử toàn bộ Patient/Tutor bằng Flask trên Windows. Chỉ thực hiện các lệnh Docker phía dưới khi chuyển sang máy có Docker Engine + Compose hoặc chạy workflow GitHub. Không cài `requirements-docker.txt` vào Windows; Gunicorn trong gói này dành cho Linux/container.

## 1. Các file phải đặt ở đâu?

Root dự án là thư mục chứa `medquest.py`, `requirements.txt` và thư mục `app`.

| File | Vị trí | Vai trò |
|---|---|---|
| `Dockerfile` | Root | Image Python 3.12, user không phải root, hai target test/runtime |
| `compose.yaml` | Root | Web, cổng localhost 8000, volume `medquest_data` |
| `.dockerignore` | Root | Loại key, DB, backup và môi trường local khỏi build context |
| `.env.docker.example` | Root | Mẫu cấu hình cho máy chạy Docker; không chứa key thật |
| `requirements-docker.txt` | Root | Bộ thư viện hiện tại và Gunicorn 26.2.0 |
| `gunicorn.conf.py` | Root | Một worker, 4 threads, log không chứa query/cookie/body |
| `scripts/container_entrypoint.py` | Thư mục scripts | Kiểm tra DB/schema trước khi mở web |
| `scripts/backup_database.py` | Thư mục scripts | Sao lưu SQLite nhất quán và từ chối ghi đè bản sao |
| `.github/workflows/docker-check.yml` | Root repository GitHub | Kiểm tra thủ công; không publish image, không deploy |
| `.gitattributes`, `.gitignore` | Root | Quy tắc xuống dòng và bỏ qua dữ liệu riêng |

Nếu sau này repository chứa thêm một thư mục `medquest_ai/` bao ngoài source, workflow phải đặt tại `.github/workflows` của repository và các lệnh build phải chạy tại thư mục source. Cách đơn giản nhất là chọn ngay thư mục chứa `medquest.py` làm root repository.

## 2. Những việc làm ngay trên Windows, không cần Docker

- Chép các file đúng vị trí và kiểm thử AI Tutor bằng Flask.
- Giữ `.env`, database và tài khoản đang dùng.
- Xem lại file sẽ đưa lên GitHub: chỉ source, migrations, ca giả lập, tests, docs và các file đóng gói.
- Không đưa `.env`, `.env.docker`, `.venv`, SQLite, backup, log hoặc khóa vào repository.
- `.gitignore` không tự bỏ một file đã từng được Git theo dõi. Nếu sau này dùng Git, kiểm tra `git ls-files .env .env.docker "*.sqlite*" "*.db"` trước khi commit.
- Không đổi đường dẫn DB Windows sang `/data`; đường dẫn đó chỉ dùng bên trong container.

## 3. Tạo cấu hình trên máy sẽ chạy Docker

Chép `.env.docker.example` thành `.env.docker`. Nếu file thật đã có, chỉnh sửa file hiện có, không chép đè. Tạo SECRET_KEY riêng:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Điền khóa vừa tạo vào `SECRET_KEY`; giữ file riêng. Điền đúng `LLM_MODEL`, `LLM_API_KEY` và cấu hình provider đã chạy thành công. Không cần đổi sang một model khác để dùng Tutor.

Compose giới hạn cổng ở `127.0.0.1:8000`; vì đang dùng HTTP local, mẫu đặt `SESSION_COOKIE_SECURE=false`. Nếu triển khai tên miền/HTTPS sau này, cấu hình `TRUSTED_HOSTS`, cookie Secure, reverse proxy và TLS trước khi mở truy cập từ bên ngoài. Gói này chưa cấu hình các phần đó.

## 4. Chọn đúng một cách chuẩn bị database

### A. Cài mới, không cần tài khoản/hội thoại cũ

Trên máy có Docker, ở root source:

```powershell
docker compose build
docker compose run --rm web python -m flask --app medquest db upgrade
docker compose run --rm web python -m flask --app medquest create-admin --email admin@medquest.local
docker compose run --rm web python -m flask --app medquest import-cases --admin-email admin@medquest.local
docker compose run --rm web python -m flask --app medquest import-cases --admin-email admin@medquest.local data/case_updates/mq_com_01_v3.json
docker compose run --rm web python -m flask --app medquest ai check-provider
docker compose run --rm web python -m flask --app medquest ai index-cases
docker compose up -d
```

Dừng tại lệnh lỗi và xử lý trước khi chạy tiếp. Tạo admin hỏi mật khẩu tương tác, không có mật khẩu mặc định. Hai lệnh AI gọi provider thật. Ca nhập vẫn là DRAFT kiểm thử; không tự phát hành cho học viên.

### B. Giữ tài khoản/hội thoại/điểm từ Windows

Dừng Flask, đứng ở đúng root source Windows đã có `.env` đang dùng:

```powershell
python scripts\backup_database.py --output .\transfer\medquest-transfer.sqlite
```

Script đọc **đường dẫn DB hiện được app cấu hình**, kể cả DB nằm ở `instance` của thư mục cha. Dùng SQLite backup API để lấy bản sao nhất quán, không chỉ chép một file đang có WAL. Nếu đích đã tồn tại, chọn tên khác; script không ghi đè.

Chuyển riêng file backup và cấu hình bí mật sang máy Docker qua cách bạn kiểm soát; không gửi qua repository công khai. Ở root source máy Docker, đặt backup đúng `transfer/medquest-transfer.sqlite`.

Trước khi khởi tạo database ở volume mới:

```powershell
docker compose build
docker compose run --rm --volume ./transfer:/import:ro web python -c "from scripts.backup_database import backup_sqlite; backup_sqlite('/import/medquest-transfer.sqlite', '/data/medquest.sqlite')"
docker compose run --rm web python -m flask --app medquest check --db
docker compose up -d
```

Lệnh nhập từ chối nếu volume đã có `medquest.sqlite`. Khi đó giữ nguyên volume và kiểm tra dữ liệu đang có, không xóa để chạy lại. Nếu schema cũ, làm theo hướng dẫn nâng cấp có sao lưu; không dùng `stamp` hoặc `downgrade` để bỏ qua lỗi.

Nếu backup đã có chỉ mục RAG và bạn giữ nguyên cấu hình embedding, không cần index lại. Nếu đổi model embedding, phải tạo lại chỉ mục tương ứng trước khi thử Patient.

## 5. Kiểm tra, dừng và sao lưu khi container đã chạy

Mở `http://127.0.0.1:8000`.

```powershell
docker compose ps
docker compose logs --tail 80 web
docker compose exec web python -m flask --app medquest check --db
```

Healthcheck chỉ kiểm tra web trả HTTP; không gọi LLM, không chứng minh provider đang hoạt động. Entrypoint kiểm tra DB có sẵn và đúng revision trước khi chạy Gunicorn; không tự tạo bảng, reset dữ liệu, nhập ca hoặc gọi AI mỗi lần khởi động.

Dừng mà giữ database:

```powershell
docker compose down
```

**Không thêm `-v` hoặc `--volumes` trên máy đang giữ dữ liệu thật**; các tùy chọn đó xóa volume. Cũng không dùng `docker system prune --volumes` cho môi trường này.

Ví dụ sao lưu khi chạy container, chọn tên mới mỗi lần:

```powershell
docker compose exec web python scripts/backup_database.py --output /data/backups/medquest-backup-01.sqlite
docker compose cp web:/data/backups/medquest-backup-01.sqlite ./medquest-backup-01.sqlite
```

Giữ bản sao ngoài volume; không chỉ dựa vào một backup trong cùng volume.

## 6. Kiểm tra trên GitHub khi máy bạn không có Docker Desktop

File workflow được cung cấp sẵn, **chưa được chạy hay đưa lên GitHub thay bạn**.

Khi bạn tự đưa dự án lên repository sau này:

1. Đảm bảo `Dockerfile` nằm ở root repository như hướng dẫn trên.
2. Mở **Actions → Check MedQuest Docker manually → Run workflow**. Workflow cần có trên nhánh mặc định để hiện nút chạy thủ công.
3. Workflow build target test, chạy unittest trong môi trường tạm, build runtime, migration vào volume tạm và thử HTTP.
4. AI bị tắt trong workflow; không cần đưa API key thật vào GitHub Secrets.
5. Volume bị xóa ở cuối **chỉ trong runner CI dùng một lần**, không phải volume trên máy của bạn. Workflow không push image và không deploy.

Nếu kiểm tra thành công, đó là bằng chứng image build/khởi động được trên runner Linux tại thời điểm chạy. Vẫn cần kiểm tra Gemini và database thực tế trên nơi triển khai của bạn.

## 7. Giới hạn và nguồn tham khảo

Cấu hình dùng một worker để phù hợp SQLite, limiter đăng nhập trong RAM và cơ chế một thao tác AI chạy tại một thời điểm. Chưa kiểm thử tải nhiều người đồng thời; không tăng worker/replica trước khi tách limiter, khóa và lưu trữ dùng chung.

Đã kiểm tra Gunicorn trực tiếp trên Linux; chưa build/chạy image Docker trong môi trường soạn gói vì không có Docker Engine. Workflow là cách kiểm tra tiếp theo, không phải kết quả CI đã chạy.

Tài liệu chính thức đối chiếu:
- [Flask — Gunicorn](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/)
- [Gunicorn settings](https://gunicorn.org/reference/settings/)
- [Docker Python guide](https://docs.docker.com/guides/python/)
- [Docker volumes](https://docs.docker.com/engine/storage/volumes/)
- [Compose environment](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)
- [actions/checkout](https://github.com/actions/checkout)
