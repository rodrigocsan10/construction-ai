"""
Branded proposal PDF styling. Change ACCENT_HEX for company brand (default amber #D97706).
"""

from __future__ import annotations

# Primary accent (headers, rules, table headers)
ACCENT_HEX = "#D97706"

# Neutrals
TEXT_PRIMARY = (33, 33, 33)
TEXT_MUTED = (82, 82, 82)
RULE_LIGHT = (220, 220, 220)
WHITE = (255, 255, 255)
CONFIDENTIAL_RED = (185, 28, 28)

BODY_PT = 10
TITLE_PT = 22
SECTION_PT = 13
SMALL_PT = 8
LINE_HEIGHT_MM = 5.5
PAGE_MARGIN = 18


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.strip().lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def accent_rgb() -> tuple[int, int, int]:
    return hex_to_rgb(ACCENT_HEX)
