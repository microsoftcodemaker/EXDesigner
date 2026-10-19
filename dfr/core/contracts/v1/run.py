"""Analysis run record (PRD section 5.1)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from dfr.core.contracts.v1.diagnostic import Diagnostic
from dfr.core.contracts.v1.enums import RunStatus, Tier
from dfr.core.contracts.v1.spec import RunConfig


class AnalysisRun(BaseModel):
    """Immutable once ``finished_at`` is set. Re-runs create a new row with ``parent_run_id``."""

    model_config = ConfigDict(frozen=True)

    id: int | None = None
    design_version_id: int
    parent_run_id: int | None = None
    tier_level: Tier = Tier.T1
    ruleset_id: str
    ruleset_hash: str | None = None
    model_set: dict[str, str] = Field(default_factory=dict)  # module id -> version
    config: RunConfig
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus = RunStatus.PENDING
    diagnostics: tuple[Diagnostic, ...] = ()
