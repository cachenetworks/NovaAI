from __future__ import annotations

import sys
from typing import Any


def console_safe_text(value: Any) -> str:
    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return text.encode(encoding, errors="replace").decode(
            encoding, errors="replace"
        )
    except Exception:
        return text
