"""Enumerations shared by every module (PRD sections 2.3, 5.1)."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class PartClass(StrEnum):
    RESISTOR = "resistor"
    CAPACITOR = "capacitor"
    INDUCTOR = "inductor"
    DIODE = "diode"
    TRANSISTOR = "transistor"
    IC = "ic"
    CONNECTOR = "connector"
    FUSE = "fuse"
    SWITCH = "switch"
    CRYSTAL = "crystal"
    TRANSFORMER = "transformer"
    TEST_POINT = "test_point"
    OTHER = "other"
    UNKNOWN = "unknown"


class Stat(StrEnum):
    PEAK = "peak"
    RMS = "rms"
    AVG = "avg"
    MIN = "min"
    DC = "dc"


class Source(StrEnum):
    """Origin of a stress value. ``SIMULATED`` = numbers taken from an external simulator."""

    EQUATION = "equation"
    MANUAL = "manual"
    MEASURED = "measured"
    SIMULATED = "simulated"


class Tier(IntEnum):
    T1 = 1
    T2 = 2


class Scenario(StrEnum):
    NOMINAL = "nominal"
    VIN_MAX = "vin_max"
    VIN_MIN = "vin_min"
    STARTUP = "startup"
    LOAD_STEP = "load_step"


class RatingProvenance(StrEnum):
    USER = "user"
    SEED = "seed"
    API = "api"
    DATASHEET = "datasheet_pdf_manual"
    BOM_DESCRIPTION = "bom_description"


class NetKind(StrEnum):
    POWER = "power"
    GROUND = "ground"
    SIGNAL = "signal"
    UNKNOWN = "unknown"


class AutoUserProvenance(StrEnum):
    """Provenance for values the app proposes and the user may override."""

    AUTO = "auto"
    USER = "user"


class ProposalProvenance(StrEnum):
    PROPOSED = "proposed"
    USER = "user"


class PinFunctionProvenance(StrEnum):
    NETLIST = "netlist"
    SEED = "seed"
    USER = "user"
    INFERRED = "inferred"


class StageStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    STALE = "stale"


class PromptOrigin(StrEnum):
    M2 = "m2"
    M12 = "m12"
    M3 = "m3"


class PromptStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    SKIPPED = "skipped"


class DeratingStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SessionState(StrEnum):
    """Tiered-workflow state machine (PRD section 2.6)."""

    DRAFT = "draft"
    CIRCUIT_CONFIRMED = "circuit_confirmed"
    T1_RUNNING = "t1_running"
    TRIAGED = "triaged"
    T2_QUEUED = "t2_queued"
    T2_AWAITING_INPUT = "t2_awaiting_input"
    RERUN = "rerun"
    FINAL = "final"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
