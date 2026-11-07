"""Tạo cấu hình local với SECRET_KEY riêng; không in khóa và không ghi đè khóa cũ."""
from pathlib import Path
import re
import secrets


def main():
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    if target.exists():
        content = target.read_text(encoding="utf-8-sig")
        found = re.search(r"(?m)^SECRET_KEY\s*=\s*(.*?)\s*$", content)
        if found and found.group(1).strip("\"'"):
            print("Đã có .env và SECRET_KEY; giữ nguyên cấu hình hiện tại.")
            return
    else:
        content = (root / ".env.example").read_text(encoding="utf-8")
    replacement = "SECRET_KEY=" + secrets.token_urlsafe(32)
    if re.search(r"(?m)^SECRET_KEY\s*=.*$", content):
        content = re.sub(r"(?m)^SECRET_KEY\s*=.*$", replacement, content)
    else:
        content = content.rstrip() + "\n" + replacement + "\n"
    target.write_text(content, encoding="utf-8")
    print("Đã tạo cấu hình .env với khóa riêng. Không chia sẻ tệp .env.")


if __name__ == "__main__":
    main()
