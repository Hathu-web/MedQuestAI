"""Cài mới bằng đúng Python/venv hiện tại; dừng ngay khi một bước lỗi."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Tạo database, admin và nhập hai ca demo.")
    parser.add_argument("--email", default="admin@medquest.local")
    parser.add_argument("--name", default="Quản trị MedQuest")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    commands = [
        [sys.executable, str(root / "scripts/setup_local.py")],
        [sys.executable, "-m", "flask", "--app", "medquest", "db", "upgrade"],
        [sys.executable, "-m", "flask", "--app", "medquest", "create-admin", "--email", args.email, "--name", args.name],
        [sys.executable, "-m", "flask", "--app", "medquest", "import-cases", "--admin-email", args.email],
        [sys.executable, "-m", "flask", "--app", "medquest", "check", "--db"],
    ]
    for index, command in enumerate(commands, 1):
        print(f"\n[{index}/{len(commands)}] Thiết lập database", flush=True)
        result = subprocess.run(command, cwd=root, check=False)
        if result.returncode:
            print("Đã dừng tại bước lỗi. Sửa theo thông báo rồi chạy lại; không xóa database.")
            return result.returncode
    print("\nHoàn tất thiết lập. Chạy: python -m flask --app medquest run")
    print("Đăng nhập tại http://127.0.0.1:5000/auth/login bằng email và mật khẩu admin vừa tạo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
