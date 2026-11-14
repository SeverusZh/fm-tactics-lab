"""路径文本清洗单元测试。"""

from __future__ import annotations

import pytest

from fm27lab.application.source_paths import clean_path_text


@pytest.mark.parametrize(
    "value",
    [None, 0, 5, 1.5, True, False, b"/tmp/season.fm", ["/tmp/season.fm"], {"path": "/tmp/season.fm"}],
)
def test_clean_path_text_returns_none_for_non_text(value):
    assert clean_path_text(value) is None


@pytest.mark.parametrize("value", ["", "   ", "\t\n", '""', "''", '  ""  '])
def test_clean_path_text_returns_none_for_blank_text(value):
    assert clean_path_text(value) is None


def test_clean_path_text_strips_surrounding_whitespace():
    assert clean_path_text("  /tmp/season.fm \n") == "/tmp/season.fm"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('"/tmp/season.fm"', "/tmp/season.fm"),
        ("'/tmp/season.fm'", "/tmp/season.fm"),
        ('  "/tmp/season.fm"  ', "/tmp/season.fm"),
        ("\t'/tmp/season.fm'\t", "/tmp/season.fm"),
        ('"  /tmp/season.fm  "', "/tmp/season.fm"),
    ],
)
def test_clean_path_text_removes_one_quote_layer_and_trims(value, expected):
    assert clean_path_text(value) == expected


def test_clean_path_text_keeps_unpaired_quotes():
    for value in ('"/tmp/season.fm', "'/tmp/season.fm", '/tmp/season.fm"', "/tmp/season.fm'"):
        assert clean_path_text(value) == value


def test_clean_path_text_keeps_quotes_inside_path():
    assert clean_path_text('/tmp/a"b.fm') == '/tmp/a"b.fm'
    assert clean_path_text('"/tmp/a"b"') == '/tmp/a"b'
    assert clean_path_text("/tmp/a'b.fm") == "/tmp/a'b.fm"


def test_clean_path_text_keeps_normal_path():
    assert clean_path_text("/tmp/my season.fm") == "/tmp/my season.fm"
    assert clean_path_text("C:\\Games\\season.fm") == "C:\\Games\\season.fm"
