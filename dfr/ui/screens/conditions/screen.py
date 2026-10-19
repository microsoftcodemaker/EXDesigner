"""Conditions (PRD 4.1 screen 5): converter spec form, inferred L/Cout with override."""

from __future__ import annotations

from pydantic import ValidationError
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dfr.core.contracts import ConverterSpec, RoleMap
from dfr.core.db.repos import StageRepo
from dfr.core.extension import ScreenSpec
from dfr.ui.kit import heading
from dfr.ui.viewmodels.shell import ShellViewModel

SCREEN = ScreenSpec(
    id="conditions", title="Conditions", step="conditions", order=40, requires=("m2_conditions",)
)


def _spin(
    minimum: float, maximum: float, value: float, decimals: int = 3, suffix: str = ""
) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(minimum, maximum)
    s.setDecimals(decimals)
    s.setValue(value)
    s.setSuffix(suffix)
    return s


class ConditionsScreen(QWidget):
    def __init__(self, vm: ShellViewModel) -> None:
        super().__init__()
        self.vm = vm
        self.ws = vm.workspace
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(heading("Operating conditions", "title"))
        hint = QLabel(
            "Templates run at Vin_max/Iout_max and Vin_min/Iout_max. L and Cout are inferred from "
            "the confirmed roles; an override wins and is marked 'overrides BOM'."
        )
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        box = QGroupBox("Converter spec")
        form = QFormLayout(box)
        self.vin_min = _spin(0.1, 1000, 12.0, 2, " V")
        self.vin_max = _spin(0.1, 1000, 24.0, 2, " V")
        self.vout = _spin(0.1, 1000, 3.3, 3, " V")
        self.iout = _spin(0.001, 500, 1.0, 3, " A")
        self.fsw = _spin(1, 100000, 400.0, 1, " kHz")
        self.ta = _spin(-55, 200, 40.0, 1, " °C")
        for label, w in (
            ("Vin min", self.vin_min),
            ("Vin max", self.vin_max),
            ("Vout", self.vout),
            ("Iout max", self.iout),
            ("fsw", self.fsw),
            ("Ambient", self.ta),
        ):
            form.addRow(label, w)
        layout.addWidget(box)

        inf = QGroupBox("Inferred from BOM (override optional)")
        self.inf_form = QFormLayout(inf)
        self.inferred_labels: dict[str, QLabel] = {}
        self.overrides: dict[str, QLineEdit] = {}
        for name, unit in (("L", "H"), ("cout", "F"), ("dcr", "ohm"), ("esr_eq", "ohm")):
            row = QHBoxLayout()
            lab = QLabel("-")
            edit = QLineEdit()
            edit.setPlaceholderText(f"override in {unit}")
            edit.setMaximumWidth(160)
            row.addWidget(lab, 1)
            row.addWidget(edit)
            holder = QWidget()
            holder.setLayout(row)
            self.inf_form.addRow(name, holder)
            self.inferred_labels[name] = lab
            self.overrides[name] = edit
        layout.addWidget(inf)

        self.error = QLabel("")
        self.error.setProperty("role", "muted")
        layout.addWidget(self.error)
        bar = QHBoxLayout()
        self.apply = QPushButton("Apply conditions")
        self.apply.setProperty("accent", True)
        self.apply.clicked.connect(self.do_apply)
        bar.addWidget(self.apply)
        bar.addStretch(1)
        layout.addLayout(bar)
        layout.addStretch(1)

        self.ws.changed.connect(lambda _: self.refresh_inferred())
        self.refresh_inferred()

    def refresh_inferred(self) -> None:
        stage = self.ws.stage
        if stage is None or stage.id is None or not self.vm.registry.has_service("infer_passives"):
            for lab in self.inferred_labels.values():
                lab.setText("confirm the circuit first")
            return
        roles: RoleMap = StageRepo(self.vm.session, self.vm.clock).role_map(stage.id)
        inferred = self.vm.registry.service("infer_passives")(self.ws.parts(), roles)
        for name, lab in self.inferred_labels.items():
            v = inferred.values.get(name)
            lab.setText(
                f"{v.value:.4g} {v.unit}  from {', '.join(v.contributing_refdes)}"
                if v
                else "not available"
            )

    def do_apply(self) -> None:
        try:
            spec = ConverterSpec(
                vin_min=self.vin_min.value(),
                vin_max=self.vin_max.value(),
                vout=self.vout.value(),
                iout_max=self.iout.value(),
                fsw=self.fsw.value() * 1e3,
                t_ambient=self.ta.value(),
            )
        except ValidationError as exc:
            self.error.setText("; ".join(e["msg"] for e in exc.errors()))
            return
        overrides: dict[str, float] = {}
        for name, edit in self.overrides.items():
            text = edit.text().strip()
            if text:
                try:
                    overrides[name] = float(text)
                except ValueError:
                    self.error.setText(f"{name}: override must be a number in SI units")
                    return
        self.error.setText("")
        self.ws.set_spec(spec, overrides)
        self.error.setText("Conditions applied. Analyze step is ready.")


def build(vm: ShellViewModel) -> QWidget:
    return ConditionsScreen(vm)
