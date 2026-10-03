"""Logging ra terminal và file (logs/app.log). Không bao giờ log khóa bí mật."""
from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False
_SECRET_RE = re.compile(r"(key=|X-VanMusic-Key[:=]\s*)[^&\s'\"]+", re.IGNORECASE)


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            record.msg = _SECRET_RE.sub(r"\1***", msg)
            record.args = ()
        except Exception:  # pragma: no cover
            pass
        return True


def setup_logging(log_dir: str | Path | None = None, level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.addFilter(_RedactFilter())
    root.addHandler(console)

    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(Path(log_dir) / "app.log", maxBytes=2_000_000,
                                 backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.addFilter(_RedactFilter())
        root.addHandler(fh)
    # googleapiclient rất ồn ở mức INFO
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
