"""M1: BOM importer and part database.

Import is a user action, not an analysis step, so this module exposes *services* rather than
a pipeline step. It owns the ``m1_part_catalog`` table (branch ``m1_bom``).
"""

from __future__ import annotations

from pathlib import Path

from dfr.api import API_VERSION, ModuleSpec
from dfr.modules.m1_bom.catalog_io import (
    catalog_rows,
    delete_dataset,
    export_catalog,
    import_catalog,
    list_datasets,
    parse_catalog,
)
from dfr.modules.m1_bom.join import join_netlist, prune_dnp
from dfr.modules.m1_bom.netlist.service import import_netlist
from dfr.modules.m1_bom.persist import persist_design
from dfr.modules.m1_bom.pins import apply_user_pinout, resolve_pin_functions, save_pinout
from dfr.modules.m1_bom.service import MODULE_ID, classify_bom, import_bom, read_bom

VERSION = "0.1.0"

MODULE = ModuleSpec(
    id=MODULE_ID,
    name="BOM importer and part database",
    version=VERSION,
    api_version=API_VERSION,
    requires=(),
    provides=(),
    optional=False,
    step=None,
    services={
        "read_bom": read_bom,
        "classify_bom": classify_bom,
        "import_bom": import_bom,
        "import_netlist": import_netlist,
        "join_netlist": join_netlist,
        "prune_dnp": prune_dnp,
        "resolve_pin_functions": resolve_pin_functions,
        "apply_user_pinout": apply_user_pinout,
        "save_pinout": save_pinout,
        "persist_design": persist_design,
        "catalog.parse": parse_catalog,
        "catalog.import": import_catalog,
        "catalog.export": export_catalog,
        "catalog.delete_dataset": delete_dataset,
        "catalog.datasets": list_datasets,
        "catalog.rows": catalog_rows,
    },
    migrations_path=Path(__file__).parent / "migrations",
    table_prefix="m1_",
)
