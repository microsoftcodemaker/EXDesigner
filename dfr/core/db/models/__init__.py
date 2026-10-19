"""Core shared tables. Module-owned tables live in their module folder (PRD rule 6)."""

from dfr.core.db.models.design import Design, DesignVersion
from dfr.core.db.models.netlist import NetRow, PinRow
from dfr.core.db.models.part import PartRow, RatingRow
from dfr.core.db.models.run import AnalysisRunRow, DiagnosticRow, EffectiveStressRow
from dfr.core.db.models.stress import StressValueRow, ValuePromptRow
from dfr.core.db.models.topology import RailRow, RoleAssignmentRow, StageRow

__all__ = [
    "AnalysisRunRow",
    "Design",
    "DesignVersion",
    "DiagnosticRow",
    "EffectiveStressRow",
    "NetRow",
    "PartRow",
    "PinRow",
    "RailRow",
    "RatingRow",
    "RoleAssignmentRow",
    "StageRow",
    "StressValueRow",
    "ValuePromptRow",
]
