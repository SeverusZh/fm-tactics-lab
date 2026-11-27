"""Register the FM27 27.1.1 game database layouts that fmsave 0.14.x does not ship.

fmsave resolves layouts by exact build. A 27.1.1 save has no `game_db` entry of
its own, so `find_layout` borrows the 27.0.0 entries, whose finance tail is five
bytes shorter than the tail 27.1.0 and 27.1.1 share. fmsave 0.14.1 already
carries a club table fallback and the matching sponsor-chain swap for unverified
27.x builds, and warns when a save is read through that fallback. This module
only registers the 27.1.0 `game_db` entries as exact for 27.1.1, so the reader
takes the right finance layout directly instead of depending on the fallback. It
does not mark the build known, so the warning stays, and it leaves every other
region, schema and layout type to fmsave's own resolution, including the silent
same-schema borrow.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any

BASE_BUILD = "27.1.0+2505117"
TARGET_BUILD = "27.1.1+2511875"
GAME_DB_REGION = "game_db"

_INSTALL_LOCK = threading.Lock()


def _registered_game_db_entries(build: str) -> tuple[Any, ...]:
    """The entries fmsave actually registers for a build's game_db region."""
    from fmsave._layouts import registered_layouts

    return tuple(
        entry
        for entry in registered_layouts()
        if getattr(entry, "build", None) == build
        and getattr(entry, "region", None) == GAME_DB_REGION
    )


def _coverage_key(entry: Any) -> tuple[str, int | None, type[Any]]:
    return (entry.region, entry.schema, type(entry.layout))


def _missing_entries(
    base_entries: tuple[Any, ...], target_entries: tuple[Any, ...]
) -> tuple[Any, ...]:
    covered = {_coverage_key(entry) for entry in target_entries}
    return tuple(entry for entry in base_entries if _coverage_key(entry) not in covered)


def install() -> bool:
    """Clone the 27.1.0 `game_db` layouts 27.1.1 lacks and report full coverage.

    The fmsave registry is the source of truth: layouts another module already
    registers for 27.1.1 are kept, and only the coverage gaps are cloned. Safe
    to call repeatedly and safe when fmsave or its layout module is absent or
    changes shape: a failure only leaves the borrowed-layout behavior in place.
    """
    try:
        from fmsave._layouts import fm27_27_1_0

        with _INSTALL_LOCK:
            base_entries = _registered_game_db_entries(BASE_BUILD)
            if not base_entries:
                return False
            missing = _missing_entries(base_entries, _registered_game_db_entries(TARGET_BUILD))
            if not missing:
                return True
            layouts = getattr(fm27_27_1_0, "LAYOUTS", None)
            if not isinstance(layouts, tuple):
                return False
            cloned = tuple(replace(entry, build=TARGET_BUILD) for entry in missing)
            fm27_27_1_0.LAYOUTS = (*layouts, *cloned)
            return not _missing_entries(base_entries, _registered_game_db_entries(TARGET_BUILD))
    except Exception:
        return False
