"""Pack extraction limits approved under decision D-06.

Authoritative reference:
- Protocol-Canary CF-02 section 7 (pack limits)
- Protocol-Canary CF-06 section 6 (release archive limits)
"""
from __future__ import annotations

MAX_FILES = 2000
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_DEPTH = 8
