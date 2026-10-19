"""Versioned exchange types. ``dfr.core.contracts`` always re-exports the current version."""

from dfr.core.contracts import v1
from dfr.core.contracts.v1 import *  # noqa: F403
from dfr.core.contracts.v1 import __all__ as _v1_all

CURRENT = v1

__all__ = [*_v1_all, "CURRENT"]  # noqa: PLE0604 - list of str at runtime
