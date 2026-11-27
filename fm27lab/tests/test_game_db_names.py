"""Game installation name database tests."""

from __future__ import annotations

import struct

import pytest

from fm27lab.adapters import game_db_names

MAGIC = b"\x03\x01tad."
SCHEMA = 3753
EN_NATIONS = (0xFF, 0xFF, None, 0x00)
EN_COMPETITIONS = (0xFF, 0xFF, 0x00)
ZH_NATIONS = (0x00, 0x00, None, 0x00)
ZH_COMPETITIONS = (0x00, 0x00, 0x00)
NATIONS = [
    (5, ["Algeria", "Algeria", "ALG", "Algerian"]),
    (40, ["São Tomé and Príncipe", "São Tomé & Príncipe", "STP", "São Toméan"]),
    (765, ["England", "England", "ENG", "English"]),
]
COMPETITIONS = [
    (1, ["Jupiler Pro League", "Jupiler Pro League", "JPL"]),
    (11, ["Premier League", "Premier League", "PL"]),
    (12, ["Sky Bet Championship", "Championship", "CHA"]),
]
ZH_NATION_NAMES = [
    (5, ["阿尔及利亚", "阿尔及利亚", "阿尔及", "阿尔及利亚"]),
    (40, ["圣多美和普林西比", "圣普", "圣普", "圣多美人"]),
    (765, ["英格兰", "英格兰", "英格", "英格兰"]),
]
ZH_COMPETITION_NAMES = [
    (1, ["“Jupiler”比利时足球甲级联赛", "“Jupiler”比甲联赛", "比甲联"]),
    (11, ["英格兰超级联赛", "英超联赛", "英超"]),
    (12, ["英格兰天空博彩冠军联赛", "英冠联赛", "英冠"]),
]


def _padded(rows, total, prefix):
    filled = list(rows)
    while len(filled) < total:
        index = len(filled)
        filled.append((10000 + index, [f"{prefix}{index}"] * 3 + [f"{prefix}{index}"]))
    return filled


def _encoded(value: str, terminator: int | None) -> bytes:
    data = value.encode("utf8")
    return struct.pack("<I", len(data)) + data + (b"" if terminator is None else bytes([terminator]))


def _block(records, grammar, count=None):
    body = b"".join(
        struct.pack("<I", record_id)
        + b"".join(_encoded(value, terminator) for value, terminator in zip(values, grammar, strict=False))
        for record_id, values in records
    )
    return MAGIC + struct.pack("<H", SCHEMA) + struct.pack("<I", len(records) if count is None else count) + body


def _stream(nations=NATIONS, competitions=COMPETITIONS):
    return _block(_padded(nations, 120, "Nation"), EN_NATIONS) + _block(
        _padded(competitions, 600, "League"), EN_COMPETITIONS
    )


def _zh_stream():
    return _block(_padded(ZH_NATION_NAMES, 120, "国家"), ZH_NATIONS) + _block(
        _padded(ZH_COMPETITION_NAMES, 600, "联赛"), ZH_COMPETITIONS
    )


def test_parse_returns_only_requested_names():
    result = game_db_names.parse_name_tables(_stream(), {11, 12, 999}, {5, 765})

    assert result["competitions"] == {11: "Premier League", 12: "Sky Bet Championship"}
    assert result["nations"] == {5: "Algeria", 765: "England"}
    assert result["language"] == "en"


def test_parse_uses_utf8_byte_lengths():
    result = game_db_names.parse_name_tables(_stream(), set(), {40})

    assert result["nations"] == {40: "São Tomé and Príncipe"}


def test_parse_rejects_ids_from_another_table():
    with pytest.raises(ValueError):
        game_db_names.parse_name_tables(_stream(), {999999}, {5})


def test_parse_rejects_stream_without_tables():
    with pytest.raises(ValueError):
        game_db_names.parse_name_tables(b"not a name table", {1}, {1})


def test_chinese_tables_are_preferred_when_available():
    result = game_db_names.parse_name_tables(_stream() + _zh_stream(), {11, 12}, {5, 765}, language="zh")

    assert result["language"] == "zh"
    assert result["competitions"] == {11: "英超联赛", 12: "英冠联赛"}
    assert result["nations"] == {5: "阿尔及利亚", 765: "英格兰"}


def test_english_tables_ignore_chinese_names():
    result = game_db_names.parse_name_tables(_stream() + _zh_stream(), {11}, {5}, language="en")

    assert result["competitions"] == {11: "Premier League"}
    assert result["nations"] == {5: "Algeria"}


def test_preferred_language_reads_the_environment(monkeypatch):
    monkeypatch.setenv("FM27_UI_LANGUAGE", "zh-CN")
    assert game_db_names.preferred_language() == "zh"
    monkeypatch.setenv("FM27_UI_LANGUAGE", "en-GB")
    assert game_db_names.preferred_language() == "en"


def test_resolve_reports_missing_game_database(tmp_path):
    result = game_db_names.resolve(tmp_path, {11}, {5}, cache_root=tmp_path)

    assert result["source"] == "unavailable"
    assert result["competitions"] == {}


def test_resolve_reads_and_caches_a_database(tmp_path, monkeypatch):
    database = tmp_path / "game" / "shared" / "data" / "database" / "db" / "2700" / "2700_fm"
    database.mkdir(parents=True)
    raw = game_db_names._zstd().compress(_stream())
    (database / "lang_db.dat").write_bytes(raw)

    first = game_db_names.resolve(tmp_path / "game", {11}, set(), cache_root=tmp_path / "data")
    assert first["competitions"] == {11: "Premier League"}

    second = game_db_names.resolve(tmp_path / "game", {11}, set(), cache_root=tmp_path / "data")
    assert second["competitions"] == {11: "Premier League"}
    assert list((tmp_path / "data" / game_db_names.CACHE_DIRECTORY).glob("*.json"))
