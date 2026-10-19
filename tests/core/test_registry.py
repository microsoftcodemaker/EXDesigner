from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from dfr.core.contracts import API_VERSION, Severity
from dfr.core.extension import ReportSectionSpec, ScreenSpec
from dfr.core.registry import (
    ModuleSpec,
    ReportSectionRegistry,
    RunContext,
    ScreenRegistry,
    StepResult,
    build_pipeline,
    discover,
)


def spec(mid: str, requires=(), provides=(), optional=True, version="1.0.0") -> ModuleSpec:
    return ModuleSpec(
        id=mid,
        name=mid,
        version=version,
        api_version=API_VERSION,
        requires=tuple(requires),
        provides=tuple(provides),
        optional=optional,
    )


# ----------------------------------------------------------------------------- ModuleSpec


def test_module_spec_id_pattern_and_tool_tag() -> None:
    assert spec("m1_bom", version="2.3.4").tool_tag == "m1_bom@2.3.4"
    with pytest.raises(ValidationError):
        spec("Bad-Id")


# ----------------------------------------------------------------------------- pipeline


def test_pipeline_orders_by_capabilities() -> None:
    p = build_pipeline(
        [
            spec("thermal", requires=("stress",), provides=("thermal",)),
            spec("stress", requires=("parts",), provides=("stress",)),
            spec("derating", requires=("stress", "thermal"), provides=("derating",)),
        ],
        initial_capabilities=("parts",),
    )
    assert p.ids == ["stress", "thermal", "derating"]
    assert p.provides() == {"stress", "thermal", "derating"}
    assert not p.diagnostics


def test_missing_dependency_is_diagnostic_not_exception() -> None:
    p = build_pipeline(
        [
            spec("derating", requires=("stress",), provides=("derating",)),
            spec("report", requires=("derating",), provides=("report",)),
            spec("standalone", provides=("x",)),
        ]
    )
    assert p.ids == ["standalone"]
    assert set(p.skipped) == {"derating", "report"}  # transitive loss
    codes = [d.code for d in p.diagnostics]
    assert codes.count("PIPELINE_MISSING_DEP") == 2
    assert all(d.severity is Severity.WARNING for d in p.diagnostics)


def test_required_module_missing_dep_is_error() -> None:
    p = build_pipeline([spec("core_step", requires=("nothing",), optional=False)])
    assert p.diagnostics[0].severity is Severity.ERROR


def test_disabled_by_config() -> None:
    p = build_pipeline([spec("a", provides=("a",)), spec("b", provides=("b",))], enabled=["a"])
    assert p.ids == ["a"]
    assert p.skipped["b"] == "disabled by config"


def test_duplicate_provider_reported() -> None:
    p = build_pipeline([spec("a", provides=("x",)), spec("b", provides=("x",))])
    assert any(d.code == "PIPELINE_DUPLICATE_PROVIDER" for d in p.diagnostics)
    assert set(p.ids) == {"a", "b"}


def test_cycle_detected() -> None:
    p = build_pipeline(
        [spec("a", requires=("b",), provides=("a",)), spec("b", requires=("a",), provides=("b",))]
    )
    assert p.ids == []
    assert any(d.code == "PIPELINE_CYCLE" for d in p.diagnostics)


# ----------------------------------------------------------------------------- RunContext


def test_run_context_is_immutable_merge() -> None:
    ctx = RunContext({"a": 1})
    ctx2 = ctx.with_outputs({"b": 2})
    assert ctx.has("a") and not ctx.has("b")
    assert ctx2.get("b") == 2 and ctx2.capabilities() == {"a", "b"}
    assert ctx.get_or("zzz", "dflt") == "dflt"
    assert StepResult(outputs={"x": 1}).outputs == {"x": 1}


# ----------------------------------------------------------------------------- discovery


def test_builtin_discovery_finds_example_module_without_central_edits() -> None:
    """MOD-02: the _example folder is found purely by scanning dfr/modules."""
    result = discover(entry_points=False)
    ids = [m.id for m in result.modules]
    # The example module is optional; CI deletes it. Either outcome is valid, but never an error.
    assert not [d for d in result.diagnostics if d.severity is Severity.ERROR]
    if "example" in ids:
        ex = result.by_id()["example"]
        assert ex.step is not None
        assert ex.migrations_path is not None and ex.migrations_path.is_dir()


def _write_plugin(folder: Path, name: str, body: str) -> None:
    (folder / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")


def test_user_plugin_dir_loads_and_rejects_api_mismatch(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "good",
        """
        from dfr.api import ModuleSpec, API_VERSION
        MODULE = ModuleSpec(id="plug_good", name="g", version="0.1", api_version=API_VERSION,
                            provides=("g",))
        """,
    )
    _write_plugin(
        tmp_path,
        "old",
        """
        from dfr.api import ModuleSpec
        MODULE = ModuleSpec(id="plug_old", name="o", version="0.1", api_version="0")
        """,
    )
    _write_plugin(tmp_path, "broken", "raise RuntimeError('boom')\n")
    _write_plugin(tmp_path, "notspec", "MODULE = 42\n")

    result = discover(packages=(), entry_points=False, plugin_dir=tmp_path)
    assert [m.id for m in result.modules] == ["plug_good"]
    codes = sorted(d.code for d in result.diagnostics if d.severity is Severity.ERROR)
    assert codes == ["PLUGIN_API_MISMATCH", "PLUGIN_BAD_SPEC", "PLUGIN_IMPORT_FAILED"]
    assert any(d.code == "PLUGIN_UNSIGNED" for d in result.diagnostics)


def test_duplicate_plugin_id_rejected(tmp_path: Path) -> None:
    body = """
        from dfr.api import ModuleSpec, API_VERSION
        MODULE = ModuleSpec(id="dup", name="d", version="1", api_version=API_VERSION)
        """
    _write_plugin(tmp_path, "a_first", body)
    _write_plugin(tmp_path, "b_second", body)
    result = discover(packages=(), entry_points=False, plugin_dir=tmp_path)
    assert len(result.modules) == 1
    assert any(d.code == "PLUGIN_DUPLICATE_ID" for d in result.diagnostics)


def test_plugin_can_register_screens_and_sections(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "ui",
        """
        from dfr.api import ModuleSpec, API_VERSION, ScreenSpec, ReportSectionSpec
        MODULE = ModuleSpec(id="withui", name="u", version="1", api_version=API_VERSION)
        SCREENS = [ScreenSpec(id="s1", title="S", step="analyze", requires=("withui",))]
        REPORT_SECTIONS = [ReportSectionSpec(id="r1", title="R", order=5, requires=("withui",))]
        """,
    )
    result = discover(packages=(), entry_points=False, plugin_dir=tmp_path)
    assert [s.id for s in result.screens] == ["s1"]
    assert [r.id for r in result.report_sections] == ["r1"]


# ----------------------------------------------------------------------------- catalogs


def test_screen_registry_hides_screens_whose_module_is_absent() -> None:
    reg = ScreenRegistry(
        [
            ScreenSpec(id="home", title="Home", step="design", order=0),
            ScreenSpec(id="fmea", title="FMEA", step="analyze", order=50, requires=("m9",)),
            ScreenSpec(id="results", title="Results", step="analyze", order=10),
        ]
    )
    assert [s.id for s in reg.visible(present_modules=[])] == ["results", "home"]
    assert [s.id for s in reg.visible(present_modules=["m9"])] == ["results", "fmea", "home"]
    reg.unregister("home")
    assert "home" not in reg


def test_report_registry_orders_sections() -> None:
    reg = ReportSectionRegistry(
        [
            ReportSectionSpec(id="b", title="B", order=2),
            ReportSectionSpec(id="a", title="A", order=1),
            ReportSectionSpec(id="mc", title="MC", order=3, requires=("m10",)),
        ]
    )
    assert [s.id for s in reg.available([])] == ["a", "b"]
    assert len(reg) == 3 and reg.get("mc") is not None
