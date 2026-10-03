#!/usr/bin/env python
"""Chèn tính năng AI Dự Báo vào index.html của VanMusic (không ghi đè file gốc).

Ví dụ:
    python scripts/inject_vanmusic_predictor.py --input index.html --output index-with-predictor.html
    python scripts/inject_vanmusic_predictor.py --input index.html --dry-run
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

VM_DIR = Path(__file__).resolve().parents[1] / "integrations" / "vanmusic"
MARK_CSS = ("/* VANMUSIC AI PREDICTOR CSS START */", "/* VANMUSIC AI PREDICTOR CSS END */")
MARK_MENU = ("<!-- VANMUSIC AI PREDICTOR MENU START -->", "<!-- VANMUSIC AI PREDICTOR MENU END -->")
MARK_MOBILE = ("<!-- VANMUSIC AI PREDICTOR MOBILE MENU START -->", "<!-- VANMUSIC AI PREDICTOR MOBILE MENU END -->")
MARK_SECTION = ("<!-- VANMUSIC AI PREDICTOR START -->", "<!-- VANMUSIC AI PREDICTOR END -->")
MARK_JS = ("<!-- VANMUSIC AI PREDICTOR SCRIPTS START -->", "<!-- VANMUSIC AI PREDICTOR SCRIPTS END -->")
MARK_SWITCH = "/* VANMUSIC AI PREDICTOR SWITCHTAB HOOK */"


class InjectError(Exception):
    pass


def read(name: str) -> str:
    p = VM_DIR / name
    if not p.exists():
        raise InjectError(f"Thiếu file tích hợp: {p}")
    return p.read_text(encoding="utf-8")


def wrap(block: tuple[str, str], body: str) -> str:
    return f"{block[0]}\n{body.strip()}\n{block[1]}"


def find_element_end(html: str, start: int, tag: str) -> int:
    """Trả về vị trí ngay sau thẻ đóng tương ứng của phần tử bắt đầu tại start (đếm lồng nhau)."""
    pat = re.compile(rf"<(/?){tag}\b[^>]*?(/?)>", re.I)
    depth = 0
    for m in pat.finditer(html, start):
        if m.group(2) == "/" and not m.group(1):
            continue
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return m.end()
    raise InjectError(f"Không tìm được thẻ đóng </{tag}>.")


def clone_menu_item(html: str, call_regex: str, new_call: str, label: str, what: str) -> tuple[int, str]:
    """Tìm phần tử menu hiện có chứa lời gọi (switchTab / openMobileSection), nhân bản thành mục mới.
    Trả về (vị trí chèn, HTML mục mới) - chèn ngay sau mục cuối cùng tìm được."""
    tag_re = re.compile(rf"<([a-zA-Z][\w-]*)\b[^>]*\bonclick\s*=\s*(\"[^\"]*{call_regex}[^\"]*\"|'[^']*{call_regex}[^']*')[^>]*>", re.I)
    matches = list(tag_re.finditer(html))
    if not matches:
        raise InjectError(f"Không tìm thấy mục menu {what} (không có phần tử onclick chứa {call_regex}).")
    # Ưu tiên mục nằm cùng khối với mục 'chart'/'history' nếu có, mặc định lấy mục cuối cùng.
    last = matches[-1]
    end = find_element_end(html, last.start(), last.group(1))
    item = html[last.start():end]
    item = re.sub(r"(switchTab\(\s*)(['\"])\w[\w-]*\2", r"\1'predictor'", item, count=1)
    item = re.sub(r"(openMobileSection\(\s*)(['\"])\w[\w-]*\2", r"\1'predictor'", item, count=1)
    item = re.sub(r"\bactive\b", "", item)  # mục mới không được active sẵn
    item = re.sub(r"class=\"\s*\"", "", item)
    item = re.sub(r"class=\"([^\"]*?)\s+\"", r'class="\1"', item)
    # Đổi icon Font Awesome (dạng "fas fa-xxx" / "fa-solid fa-xxx") và nhãn văn bản
    item = re.sub(r'(<i\b[^>]*class="[^"]*?\b(?:fas|far|fa-solid)\s+)fa-[\w-]+', r"\1fa-chart-line", item, count=1)
    texts = list(re.finditer(r">([^<>]*\S[^<>]*)<", item))
    if texts:
        t = texts[-1]
        item = item[:t.start(1)] + " " + label + " " + item[t.end(1):]
    return end, "\n" + wrap(MARK_MENU if what.startswith("máy tính") else MARK_MOBILE, item)


def find_insert_after_last_section(html: str) -> int:
    """Vị trí chèn tab-predictor: ngay sau page-section cuối cùng bên trong main-content."""
    m = re.search(r"<(\w+)\b[^>]*\bid\s*=\s*[\"']main-content[\"'][^>]*>|<(\w+)\b[^>]*\bclass\s*=\s*[\"'][^\"']*\bmain-content\b[^\"']*[\"'][^>]*>", html, re.I)
    if not m:
        raise InjectError("Không tìm thấy phần tử main-content.")
    tag = m.group(1) or m.group(2)
    end = find_element_end(html, m.start(), tag)
    inner_end = html.rfind("</", m.end(), end)  # ngay trước thẻ đóng của main-content
    sec = re.compile(r"<(section|div)\b[^>]*\bclass\s*=\s*[\"'][^\"']*\bpage-section\b[^\"']*[\"'][^>]*>", re.I)
    last = None
    for s in sec.finditer(html, m.end(), inner_end):
        # chỉ lấy page-section cấp trực tiếp: bỏ qua những phần tử nằm trong page-section trước đó
        if last is not None and s.start() < last:
            continue
        last = find_element_end(html, s.start(), s.group(1))
    return last if last is not None else inner_end


def inject(html: str) -> tuple[str, list[str]]:
    log: list[str] = []
    if MARK_SECTION[0] in html or "id=\"tab-predictor\"" in html:
        raise InjectError("File đã có tính năng AI Dự Báo (marker/tab-predictor tồn tại). Không chèn lần hai.")

    css = read("vanmusic-predictor.css")
    section = read("vanmusic-section.html")
    style_close = html.rfind("</style>")
    body_close = html.rfind("</body>")
    if style_close < 0:
        raise InjectError("Không tìm thấy thẻ </style>.")
    if body_close < 0:
        raise InjectError("Không tìm thấy thẻ </body>.")
    if "function switchTab" not in html:
        raise InjectError("Không tìm thấy hàm switchTab trong file.")

    edits: list[tuple[int, str]] = []  # (vị trí, nội dung chèn) - áp dụng từ cuối lên đầu
    edits.append((style_close, "\n" + wrap(MARK_CSS, css) + "\n"))
    log.append("CSS: chèn trước </style> cuối cùng")

    pos, menu = clone_menu_item(html, r"switchTab\(", "predictor", "AI Dự Báo", "máy tính")
    edits.append((pos, menu))
    log.append("Menu máy tính: nhân bản từ mục switchTab hiện có")

    pos, mobile = clone_menu_item(html, r"openMobileSection\(", "predictor", "AI Dự Báo", "điện thoại")
    edits.append((pos, mobile))
    log.append("Menu điện thoại: nhân bản từ mục openMobileSection hiện có")

    edits.append((find_insert_after_last_section(html), "\n" + section.strip() + "\n"))
    log.append("tab-predictor: chèn cạnh các page-section trong main-content")

    scripts = ("<script src=\"vanmusic-config.js\"></script>\n<script src=\"vanmusic-api-client.js\"></script>\n"
               "<script src=\"vanmusic-predictor.js\"></script>")
    edits.append((body_close, wrap(MARK_JS, scripts) + "\n"))
    log.append("Scripts: chèn trước </body>")

    for pos, text in sorted(edits, key=lambda e: e[0], reverse=True):
        html = html[:pos] + text + html[pos:]

    # Hook tối thiểu trong switchTab
    m = re.search(r"function\s+switchTab\s*\(([^)]*)\)\s*\{", html)
    hook = (f"\n    {MARK_SWITCH}\n    if (typeof tabName !== 'undefined' && tabName === 'predictor' && window.initializeVanMusicPredictor) "
            f"{{ window.initializeVanMusicPredictor(); }}\n")
    args = [a.strip() for a in m.group(1).split(",")]
    if not args or args[0] != "tabName":
        hook = hook.replace("tabName", args[0] if args and args[0] else "tabName")
    html = html[:m.end()] + hook + html[m.end():]
    log.append("switchTab: thêm hook khởi tạo cho 'predictor' (chỉ 1 dòng điều kiện)")
    return html, log


def main() -> int:
    ap = argparse.ArgumentParser(description="Chèn AI Dự Báo vào index.html VanMusic")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default="index-with-predictor.html")
    ap.add_argument("--dry-run", action="store_true", help="Chỉ kiểm tra và báo cáo, không ghi file")
    ap.add_argument("--backup", action="store_true", help="Tạo bản sao lưu file gốc (.bak-YYYYmmdd-HHMMSS)")
    a = ap.parse_args()

    src, out = Path(a.input), Path(a.output)
    if not src.exists():
        print(f"LỖI: không tìm thấy file đầu vào {src}")
        return 2
    if out.resolve() == src.resolve():
        print("LỖI: --output không được trùng --input (không ghi đè file gốc).")
        return 2
    try:
        html = src.read_text(encoding="utf-8")
        new_html, log = inject(html)
    except (InjectError, UnicodeDecodeError) as e:
        print(f"DỪNG: {e}")
        return 1

    for line in log:
        print(" -", line)
    if a.dry_run:
        print("DRY-RUN: mọi vị trí đều tìm thấy, chưa ghi file.")
        return 0
    if a.backup:
        bak = src.with_name(f"{src.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(src, bak)
        print("Đã sao lưu:", bak)
    out.write_text(new_html, encoding="utf-8", newline="")
    print(f"XONG: đã tạo {out}")
    print("Nhớ copy vanmusic-config.js (từ vanmusic-config.example.js), vanmusic-api-client.js, vanmusic-predictor.js cạnh file HTML.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
