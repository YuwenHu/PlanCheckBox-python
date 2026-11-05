"""日期与文本格式化工具（与 HTML 版 Model 的显示口径保持一致）。"""
from __future__ import annotations

import datetime as dt
import re

WEEK_CN = ("周日", "周一", "周二", "周三", "周四", "周五", "周六")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_WEEK_LABEL = re.compile(r"^第(\d+)周$")
_CN_DIGITS = "零一二三四五六七八九"


def parse_iso_date(value) -> dt.date | None:
    """严格解析 YYYY-MM-DD；其它格式一律视为非法。"""
    if not isinstance(value, str):
        return None
    m = _ISO_DATE.match(value.strip())
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def iso_date(d: dt.date) -> str:
    return d.isoformat()


def add_days(d: dt.date, n: int) -> dt.date:
    return d + dt.timedelta(days=n)


def month_label(month_id: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})$", str(month_id or ""))
    return f"{m.group(1)}年{int(m.group(2))}月" if m else str(month_id or "")


def fmt_md(d: dt.date, now: dt.date | None = None) -> str:
    now = now or dt.date.today()
    year = f"{d.year}年" if d.year != now.year else ""
    return f"{year}{d.month}月{d.day}日"


def fmt_range(start: dt.date, end: dt.date) -> str:
    """跨年补全两年年份；同年只写月日。"""
    if start.year != end.year:
        return f"{start.year}年{start.month}月{start.day}日 ~ {end.year}年{end.month}月{end.day}日"
    return f"{start.month}月{start.day}日 ~ {end.month}月{end.day}日"


def fmt_minutes(minutes: int) -> str:
    if not minutes:
        return "未填时长"
    if minutes < 60:
        return f"{minutes} 分钟"
    h, r = divmod(minutes, 60)
    return f"{h} 小时 {r} 分" if r else f"{h} 小时"


def _cn_number(n: int) -> str:
    if n <= 0:
        return str(n)
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return "十" + (_CN_DIGITS[n % 10] if n % 10 else "")
    if n < 100:
        return _CN_DIGITS[n // 10] + "十" + (_CN_DIGITS[n % 10] if n % 10 else "")
    return str(n)


def week_label(label: str) -> str:
    """第1周 → 第一周，与设计稿的周标题口径一致。"""
    m = _WEEK_LABEL.match(str(label or "").strip())
    if not m:
        return str(label or "")
    return "第" + _cn_number(int(m.group(1))) + "周"


def weekday_text(d: dt.date) -> str:
    return WEEK_CN[d.isoweekday() % 7]


def parse_dt(value) -> dt.datetime | None:
    """解析 doneAt 一类时间戳；兼容 Z、+08:00、无时区。"""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def local_date(value) -> dt.date | None:
    """doneAt 的本地日期：带时区换算到本机时区，无时区按原值。"""
    d = parse_dt(value)
    if d is None:
        return None
    if d.tzinfo is not None:
        d = d.astimezone()
    return d.date()


def time_text(value, now: dt.date | None = None) -> str:
    parsed = parse_dt(value)
    if parsed is None:
        return ""
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    now = now or dt.date.today()
    year = f"{parsed.year}年" if parsed.year != now.year else ""
    return f"{year}{parsed.month}月{parsed.day}日 {parsed:%H:%M}"


def now_local_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")
