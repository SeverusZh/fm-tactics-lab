from pathlib import Path

import pytest

from fm27lab import sidecar
from fm27lab.config import Settings


def test_endpoint_is_removed_when_acl_restriction_fails(tmp_path: Path, monkeypatch):
    settings = Settings.create(data_dir=tmp_path, token="f" * 64)

    def fail(_path: Path) -> None:
        raise RuntimeError("acl failure")

    monkeypatch.setattr(sidecar, "restrict_permissions", fail)
    with pytest.raises(RuntimeError, match="acl failure"):
        sidecar.write_endpoint(settings, 12345)
    assert not settings.endpoint_path.exists()
    assert not settings.endpoint_path.with_name("endpoint.json.tmp").exists()
