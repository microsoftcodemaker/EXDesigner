"""Design tokens: the only file in ``dfr/ui`` allowed to contain color literals (MOD-08).

Two palettes. ``DARK`` (default) follows the Altium Designer workspace: near-black canvas,
dark-gray panels, light text, one accent. Status colors use the Okabe-Ito colorblind-safe
set and are never the only carrier of meaning (text labels and hatch patterns accompany
them, PRD 4.3).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatusColors:
    pass_: str
    warn: str
    fail: str
    unknown: str
    info: str


@dataclass(frozen=True)
class TierColors:
    tier1: str  # hollow marker
    tier2: str  # solid marker


@dataclass(frozen=True)
class Palette:
    name: str
    canvas: str  # document / central area background
    panel: str  # dock panels, toolbars
    panel_alt: str  # alternating rows, headers
    surface: str  # cards, inputs
    border: str
    text: str
    text_muted: str
    text_disabled: str
    accent: str
    accent_text: str
    selection: str
    hover: str
    status: StatusColors
    tier: TierColors


OKABE_ITO = StatusColors(
    pass_="#009E73",  # bluish green
    warn="#E69F00",  # orange
    fail="#D55E00",  # vermillion
    unknown="#999999",
    info="#56B4E9",  # sky blue
)
TIERS = TierColors(tier1="#56B4E9", tier2="#CC79A7")

DARK = Palette(
    name="dark",
    canvas="#1E1E1E",
    panel="#2D2D30",
    panel_alt="#252526",
    surface="#333337",
    border="#3F3F46",
    text="#F1F1F1",
    text_muted="#A0A0A0",
    text_disabled="#6D6D6D",
    accent="#3C9DD0",
    accent_text="#FFFFFF",
    selection="#264F78",
    hover="#3E3E42",
    status=OKABE_ITO,
    tier=TIERS,
)

LIGHT = Palette(
    name="light",
    canvas="#FFFFFF",
    panel="#F3F3F3",
    panel_alt="#E8E8E8",
    surface="#FFFFFF",
    border="#CCCCCC",
    text="#1A1A1A",
    text_muted="#5F5F5F",
    text_disabled="#9A9A9A",
    accent="#0072B2",
    accent_text="#FFFFFF",
    selection="#CCE4F7",
    hover="#E5E5E5",
    status=OKABE_ITO,
    tier=TIERS,
)

PALETTES = {p.name: p for p in (DARK, LIGHT)}
DEFAULT_PALETTE = DARK


@dataclass(frozen=True)
class Spacing:
    xs: int = 4
    sm: int = 6
    md: int = 10
    lg: int = 16
    xl: int = 24


@dataclass(frozen=True)
class TypeScale:
    body: int = 9
    small: int = 8
    heading: int = 11
    title: int = 14
    family: str = "Segoe UI"
    mono_family: str = "Consolas"


SPACING = Spacing()
TYPE = TypeScale()

STATUS_LABELS = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "unknown": "UNKNOWN"}
TIER_LABELS = {1: "T1", 2: "T2"}
SOURCE_LABELS = {"equation": "eq", "manual": "man", "measured": "meas", "simulated": "sim"}
# Hatch patterns for charts so status survives black-and-white printing.
STATUS_HATCH = {"pass": "", "warn": "//", "fail": "xx", "unknown": ".."}


def status_color(palette: Palette, status: str) -> str:
    return {
        "pass": palette.status.pass_,
        "warn": palette.status.warn,
        "fail": palette.status.fail,
        "unknown": palette.status.unknown,
        "info": palette.status.info,
    }.get(status, palette.text_muted)
