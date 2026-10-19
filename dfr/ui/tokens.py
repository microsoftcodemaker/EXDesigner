"""Design tokens: the only file in ``dfr/ui`` allowed to contain color literals (MOD-08).

Status colors use the Okabe-Ito colorblind-safe palette; status is never conveyed by
color alone (text labels and hatch patterns accompany it, PRD section 4.3).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatusColors:
    pass_: str = "#009E73"  # bluish green
    warn: str = "#E69F00"  # orange
    fail: str = "#D55E00"  # vermillion
    unknown: str = "#999999"
    info: str = "#0072B2"  # blue


@dataclass(frozen=True)
class TierColors:
    tier1: str = "#56B4E9"  # sky blue, hollow marker
    tier2: str = "#CC79A7"  # reddish purple, solid marker


@dataclass(frozen=True)
class Palette:
    background: str = "#FFFFFF"
    surface: str = "#F5F5F5"
    border: str = "#D0D0D0"
    text: str = "#1A1A1A"
    text_muted: str = "#5F5F5F"
    accent: str = "#0072B2"
    status: StatusColors = StatusColors()
    tier: TierColors = TierColors()


@dataclass(frozen=True)
class Spacing:
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24


@dataclass(frozen=True)
class TypeScale:
    body: int = 10
    small: int = 9
    heading: int = 13
    title: int = 16
    mono_family: str = "Consolas"
    family: str = "Segoe UI"


PALETTE = Palette()
SPACING = Spacing()
TYPE = TypeScale()

STATUS_LABELS = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "unknown": "UNKNOWN"}
TIER_LABELS = {1: "T1", 2: "T2"}
SOURCE_LABELS = {
    "equation": "eq",
    "manual": "man",
    "measured": "meas",
    "simulated": "sim",
}
