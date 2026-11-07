"""HTTP có giới hạn thời gian/kích thước, không log key hay nội dung lỗi provider."""
import json
import time
from urllib.parse import urlsplit

import requests
from .errors import AIError


def endpoint(base, suffix):
    parsed = urlsplit(base)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise AIError("Địa chỉ API chưa hợp lệ. Kiểm tra BASE_URL trong .env.", "AI_CONFIG", 503)
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise AIError("API từ xa cần HTTPS.", "AI_CONFIG", 503)
    return base.rstrip("/") + "/" + suffix.lstrip("/")


def post_json(url, payload, key, timeout):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    start = time.monotonic()
    try:
        with requests.Session() as client:
            client.trust_env = False  # Không tự dùng .netrc để gửi thông tin đăng nhập khác.
            with client.post(url, json=payload, headers=headers, timeout=(min(10, timeout), timeout),
                             allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    code = response.status_code
                    detail = {503: "Dịch vụ đang quá tải hoặc tạm không sẵn sàng. Đợi rồi chủ động thử lại.",
                        429: "Đã chạm giới hạn tần suất hoặc hạn mức của provider.",
                        401: "Thông tin xác thực không được chấp nhận. Kiểm tra API key.",
                        403: "Provider từ chối quyền truy cập. Kiểm tra quyền key và trạng thái dự án.",
                        402: "Provider yêu cầu kiểm tra thanh toán hoặc số dư.",
                        404: "Không tìm thấy model hoặc địa chỉ API.",
                        400: "Provider không chấp nhận tham số yêu cầu hoặc cấu hình model."}.get(code,
                        "Provider chưa xử lý được yêu cầu. Kiểm tra trạng thái dịch vụ và cấu hình.")
                    raise AIError(f"Dịch vụ AI trả HTTP {code}. {detail}",
                                  f"AI_HTTP_{code}", 503, uncertain=code >= 500)
                chunks, size = [], 0
                for chunk in response.iter_content(8192):
                    size += len(chunk)
                    if size > 4 * 1024 * 1024 or time.monotonic() - start > timeout:
                        raise AIError("Phản hồi AI vượt giới hạn. Tải lại lượt trước khi thử lại.", "AI_RESPONSE_LIMIT", 503, True)
                    chunks.append(chunk)
                result = json.loads(b"".join(chunks))
                if not isinstance(result, dict):
                    raise ValueError("object required")
                return result
    except requests.RequestException as exc:
        raise AIError("Không nhận được phản hồi AI. Kiểm tra kết nối rồi tải lại lượt; không tự gửi lặp.",
                      "AI_NETWORK", 503, True) from exc
    except (ValueError, UnicodeError) as exc:
        raise AIError("Dịch vụ AI trả dữ liệu không hợp lệ.", "AI_BAD_RESPONSE", 503, True) from exc
