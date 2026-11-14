"""读取引擎工作区或数据目录中的运行时目录快照。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CATALOG_FILE_NAME = "catalog.json"
NATIVE_DIRECTORY_NAME = "fm27_native"
CATALOG_ERROR = "目录文件无效"
REQUIRED_SECTIONS = ("positions", "roles", "team_instructions", "mentalities")
OPTIONAL_SECTIONS = ("attributes", "player_instructions")


class CatalogRepository:
    def __init__(self, engine_root: Path | None, data_dir: Path) -> None:
        self._engine_root = Path(engine_root) if engine_root is not None else None
        self._data_dir = Path(data_dir)

    def candidates(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        if self._engine_root is not None:
            paths.append(self._engine_root / NATIVE_DIRECTORY_NAME / CATALOG_FILE_NAME)
            paths.append(self._engine_root / CATALOG_FILE_NAME)
        paths.append(self._data_dir / CATALOG_FILE_NAME)
        return tuple(paths)

    def load(self) -> dict[str, Any] | None:
        document = self.load_document()
        if document is None:
            return None
        for section in REQUIRED_SECTIONS:
            if not isinstance(document.get(section), list):
                raise ValueError(CATALOG_ERROR)
        snapshot: dict[str, Any] = {section: list(document[section]) for section in REQUIRED_SECTIONS}
        for section in OPTIONAL_SECTIONS:
            if section in document:
                snapshot[section] = document[section]
        return snapshot

    def load_document(self) -> dict[str, Any] | None:
        for path in self.candidates():
            if path.is_file():
                return self._read(path)
        return None

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(CATALOG_ERROR) from error
        if not isinstance(value, Mapping):
            raise ValueError(CATALOG_ERROR)
        return dict(value)
