"""统一日志（S1-06 日志脱敏）。

所有 handler 走 RedactingFilter，确保凭证不落日志。
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from apps.core.credentials import redact


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            record.msg = redact(msg)
            record.args = ()
        except Exception:
            pass
        return True


def setup_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("vidlearn")
    if root.handlers:
        return root
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.addFilter(RedactingFilter())

    fh = RotatingFileHandler(log_dir / "vidlearn.log", maxBytes=5_000_000,
                             backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(RedactingFilter())

    root.addHandler(sh)
    root.addHandler(fh)
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"vidlearn.{name}")
