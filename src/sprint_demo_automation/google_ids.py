from __future__ import annotations

import re


def extract_google_file_id(value: str) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return ""

    patterns = [
        r"/presentation/d/([a-zA-Z0-9_-]+)",
        r"/spreadsheets/d/([a-zA-Z0-9_-]+)",
        r"/document/d/([a-zA-Z0-9_-]+)",
        r"/folders/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, candidate)
        if match:
            return match.group(1)

    if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", candidate):
        return candidate

    return ""
