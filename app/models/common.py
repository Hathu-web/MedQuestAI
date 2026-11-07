"""Quy ước dùng chung: thời gian UTC ISO 8601, ID nguyên, không xóa dây chuyền."""
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
