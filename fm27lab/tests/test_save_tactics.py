"""存档战术库读取适配器与存档战术流解析测试。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from fm27lab.adapters.engine_native.tactic_file import (
    IMPORT_TAC_ENVIRONMENT,
    PARSED_EVENT,
    STREAM_ERROR,
    STREAM_PROBE_BYTES,
    HostRun,
    TacticCell,
    TacticFileError,
    TacticPlan,
    parse_tactic_stream,
)
from fm27lab.adapters.save_fmsave.tactics import (
    PRESET_TACTIC_SIGNATURE,
    TACTICS_UNSUPPORTED_ERROR,
    USER_TACTIC_SIGNATURE,
    TacticsSource,
    read_tactic_stream,
    read_tactics,
)

LIBRARY_SIGNATURE = bytes.fromhex("2244001b00000000")
DISCOVERED_SIGNATURE = bytes.fromhex("2244001b00020009")


@dataclass(frozen=True)
class FakeLayout:
    user_signature: bytes = LIBRARY_SIGNATURE
    alternate_signature: bytes = LIBRARY_SIGNATURE
    preset_signature: bytes = LIBRARY_SIGNATURE


@dataclass(frozen=True)
class FakeRow:
    name: str
    style_name: str = "Control"
    mentality: object = None
    club_uid: int | None = 7
    club_name: str | None = "Sev"
    team_slot: int | None = 0


@dataclass(frozen=True)
class FakeRecord:
    name: str
    walk_complete: bool
    oop_index_permutation: bool


def encode_block(signature: bytes, name: str, flags: int = 3, trailer: bytes = b"") -> bytes:
    encoded = name.encode("utf-8")
    return signature + len(encoded).to_bytes(4, "little") + encoded + bytes([flags]) + trailer


def fake_read_record(section, start, end, layout, file_name):
    cursor = start + len(layout.user_signature)
    if cursor + 4 > end:
        raise ValueError("record truncated")
    length = int.from_bytes(section[cursor : cursor + 4], "little")
    name_start = cursor + 4
    name_end = name_start + length
    if name_end + 1 > end:
        raise ValueError("record truncated")
    return FakeRecord(
        name=section[name_start:name_end].decode("utf-8"),
        walk_complete=bool(section[name_end] & 1),
        oop_index_permutation=bool(section[name_end] & 2),
    )


def loader_of(section: bytes, rows=(), layout=None):
    source = TacticsSource(
        section=section,
        layout=FakeLayout() if layout is None else layout,
        rows=tuple(rows),
        file_name="save.fm",
    )

    def load(path):
        return source

    return load


def read_items(section: bytes, rows):
    return read_tactics(Path("save.fm"), loader=loader_of(section, rows), read_record=fake_read_record)


def read_stream(section: bytes, rows, index: int):
    return read_tactic_stream(
        Path("save.fm"),
        index,
        loader=loader_of(section, rows),
        read_record=fake_read_record,
    )


def test_read_tactics_pairs_rows_by_name_and_reports_stream_flag():
    section = encode_block(USER_TACTIC_SIGNATURE, "Alpha", 3, b"\x01") + encode_block(
        USER_TACTIC_SIGNATURE, "Beta", 3, b"\x02"
    )
    rows = (
        FakeRow(name="Alpha", mentality=SimpleNamespace(raw=5), team_slot=0),
        FakeRow(name="Beta", style_name="Press", mentality=SimpleNamespace(raw=4), team_slot=1),
        FakeRow(name="Gamma", mentality=SimpleNamespace(raw=3), team_slot=0),
    )

    items = read_items(section, rows)

    assert [item.index for item in items] == [0, 1, 2]
    assert [item.name for item in items] == ["Alpha", "Beta", "Gamma"]
    assert [item.has_stream for item in items] == [True, True, False]
    assert items[0].style == "Control"
    assert items[0].mentality == 5
    assert items[0].club_uid == 7
    assert items[0].club_name == "Sev"
    assert items[0].team_slot == 0
    assert items[1].style == "Press"
    assert items[1].mentality == 4
    assert items[1].team_slot == 1


def test_read_tactics_scans_user_and_preset_signatures_together():
    section = (
        encode_block(USER_TACTIC_SIGNATURE, "Alpha")
        + encode_block(USER_TACTIC_SIGNATURE, "Beta")
        + encode_block(PRESET_TACTIC_SIGNATURE, "Gamma")
    )
    rows = (FakeRow(name="Alpha"), FakeRow(name="Beta"), FakeRow(name="Gamma"))

    items = read_items(section, rows)

    assert [item.has_stream for item in items] == [True, True, True]


def test_read_tactics_falls_back_to_discovered_signature():
    section = encode_block(DISCOVERED_SIGNATURE, "Delta")
    rows = (FakeRow(name="Delta"),)

    items = read_items(section, rows)

    assert items[0].name == "Delta"
    assert items[0].has_stream is True


def test_read_tactics_ignores_incomplete_records():
    section = b"".join(
        encode_block(USER_TACTIC_SIGNATURE, name, flags)
        for name, flags in (("Walk", 1), ("Oop", 2), ("None", 0), ("Full", 3))
    )
    rows = tuple(FakeRow(name=name) for name in ("Walk", "Oop", "None", "Full"))

    items = read_items(section, rows)

    assert [item.has_stream for item in items] == [False, False, False, True]


def test_read_tactics_raises_when_no_block_can_be_validated():
    section = encode_block(USER_TACTIC_SIGNATURE, "Broken", 0) + USER_TACTIC_SIGNATURE[:6]
    rows = (FakeRow(name="Broken"),)

    with pytest.raises(ValueError) as info:
        read_items(section, rows)

    assert str(info.value) == TACTICS_UNSUPPORTED_ERROR


def test_read_tactics_returns_empty_when_save_has_no_rows():
    assert read_items(b"", ()) == ()


def test_read_tactic_stream_returns_exact_block_slice():
    first = encode_block(USER_TACTIC_SIGNATURE, "Alpha", 3, b"\x01\x02")
    second = encode_block(USER_TACTIC_SIGNATURE, "Beta", 3, b"\x03\x04\x05")
    section = first + second + b"tail"
    rows = (FakeRow(name="Alpha"), FakeRow(name="Beta"))

    assert read_stream(section, rows, 0) == first
    assert read_stream(section, rows, 1) == second + b"tail"


def test_read_tactic_stream_returns_none_for_unpaired_or_out_of_range():
    section = encode_block(USER_TACTIC_SIGNATURE, "Alpha")
    rows = (FakeRow(name="Alpha"), FakeRow(name="Beta"))

    assert read_stream(section, rows, 1) is None
    assert read_stream(section, rows, 2) is None
    assert read_stream(section, rows, -1) is None
    assert read_tactic_stream(Path("save.fm"), 0, loader=loader_of(b"", ())) is None


def test_read_tactics_pairs_repeated_names_in_order():
    first = encode_block(USER_TACTIC_SIGNATURE, "Same", 3, b"\x11")
    second = encode_block(USER_TACTIC_SIGNATURE, "Same", 3, b"\x22")
    section = first + second
    rows = (FakeRow(name="Same"), FakeRow(name="Same"))

    stream_zero = read_stream(section, rows, 0)
    stream_one = read_stream(section, rows, 1)

    assert stream_zero == first
    assert stream_one == second
    assert stream_zero != stream_one


SAVE = Path(__file__).resolve().parents[2] / "dist" / "verify" / "fm27-save.fm"


@pytest.mark.skipif(not SAVE.is_file(), reason="真实存档不存在")
def test_read_tactics_reads_real_save():
    items = read_tactics(SAVE)

    assert len(items) == 5
    assert [item.name.replace("\u200b", "") for item in items] == [
        "Sev - Mid Control Dynamic 3-4-2-1",
        "Sev - Mid Control Dynamic 3-4-2-1",
        "Sev - Mid Control Dynamic 3-4-2-1",
        "仿格拉斯纳3421战术",
        "复制自:仿格拉斯纳3421战术",
    ]
    assert [item.team_slot for item in items] == [0, 1, 2, 3, 3]
    assert all(item.has_stream for item in items)
    assert all(item.mentality == 5 for item in items)

    stream = read_tactic_stream(SAVE, 0)

    assert stream is not None
    assert stream.startswith(USER_TACTIC_SIGNATURE)
    assert len(stream) > 100


PLAN = TacticPlan(
    name="native",
    mentality=4,
    team_bits=0x1F,
    mapping=tuple(range(11)),
    phases=tuple(
        tuple(
            TacticCell(position=index, role_flags=0, pi_flags=1, target_player=-1, target_position=-1)
            for index in range(11)
        )
        for _ in range(2)
    ),
)


def parse_event(payload: bytes, *, consumed=None, accepted=True, stream_error=0, size=None) -> dict:
    return {
        "event": PARSED_EVENT,
        "accepted": accepted,
        "stream_error": stream_error,
        "consumed": len(payload) if consumed is None else consumed,
        "size": len(payload) if size is None else size,
        "mentality": PLAN.mentality,
        "team_bits": PLAN.team_bits.to_bytes(16, "little").hex(),
        "mapping": list(PLAN.mapping),
        "phases": [
            [
                {
                    "position": cell.position,
                    "role_flags": str(cell.role_flags),
                    "pi_flags": str(cell.pi_flags),
                    "target_player": cell.target_player,
                    "target_position": cell.target_position,
                }
                for cell in phase
            ]
            for phase in PLAN.phases
        ],
    }


class FakeRunner:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.payloads: list[bytes] = []
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        payload = Path(kwargs["environment"][IMPORT_TAC_ENVIRONMENT]).read_bytes()
        self.payloads.append(payload)
        self.calls.append(kwargs)
        return self.responses.pop(0)(payload)


def parse(payload: bytes, runner: FakeRunner, **kwargs) -> TacticPlan:
    return parse_tactic_stream(payload, name="Alpha", **kwargs, runner=runner)


def test_parse_tactic_stream_reads_whole_payload_in_one_pass():
    payload = b"A" * 32
    runner = FakeRunner(lambda data: HostRun(0, [parse_event(data)], ""))

    plan = parse(payload, runner)

    assert runner.payloads == [payload]
    assert plan.name == "Alpha"
    assert plan.mentality == PLAN.mentality
    assert plan.team_bits == PLAN.team_bits
    assert plan.mapping == PLAN.mapping
    assert plan.phases == PLAN.phases


def test_parse_tactic_stream_accepts_trailing_zero_padding():
    runner = FakeRunner(lambda data: HostRun(0, [parse_event(data, consumed=32, size=40)], ""))

    plan = parse(b"E" * 40, runner)

    assert plan.name == "Alpha"
    assert len(runner.payloads) == 1


def test_parse_tactic_stream_retries_exact_consumed_prefix():
    payload = bytes(range(256)) * 16
    exact = payload[:1200]

    def first(data):
        return HostRun(173, [parse_event(data, consumed=len(exact))], "")

    def second(data):
        return HostRun(0, [parse_event(data)], "")

    runner = FakeRunner(first, second)

    plan = parse(payload, runner, engine_root=Path("engine"), game_root=Path("game"))

    assert runner.payloads == [payload, exact]
    assert plan.team_bits == PLAN.team_bits


def test_parse_tactic_stream_probes_first_megabyte_only():
    payload = b"B" * (STREAM_PROBE_BYTES + 100)

    def first(data):
        return HostRun(173, [parse_event(data, consumed=777)], "")

    def second(data):
        return HostRun(0, [parse_event(data)], "")

    runner = FakeRunner(first, second)

    parse(payload, runner)

    assert len(runner.payloads[0]) == STREAM_PROBE_BYTES
    assert runner.payloads[1] == payload[:777]


def test_parse_tactic_stream_rejects_unusable_probe_record():
    runner = FakeRunner(lambda data: HostRun(173, [parse_event(data, consumed=0, accepted=False)], ""))

    with pytest.raises(TacticFileError) as info:
        parse(b"C" * 64, runner)

    assert str(info.value) == STREAM_ERROR
    assert len(runner.payloads) == 1


def test_parse_tactic_stream_rejects_missing_probe_record():
    runner = FakeRunner(lambda data: HostRun(173, [], ""))

    with pytest.raises(TacticFileError) as info:
        parse(b"G" * 64, runner)

    assert str(info.value) == STREAM_ERROR
    assert len(runner.payloads) == 1


def test_parse_tactic_stream_rejects_incomplete_second_pass():
    payload = b"D" * 128

    def first(data):
        return HostRun(173, [parse_event(data, consumed=64)], "")

    def second(data):
        return HostRun(173, [parse_event(data, consumed=32)], "")

    runner = FakeRunner(first, second)

    with pytest.raises(TacticFileError) as info:
        parse(payload, runner)

    assert str(info.value) == STREAM_ERROR
    assert len(runner.payloads) == 2


def test_parse_tactic_stream_rejects_tiny_payload():
    runner = FakeRunner()

    with pytest.raises(TacticFileError) as info:
        parse(b"short", runner)

    assert "战术流大小无效" in str(info.value)
    assert runner.payloads == []


def test_parse_tactic_stream_forwards_host_options():
    payload = b"F" * 16
    runner = FakeRunner(lambda data: HostRun(0, [parse_event(data)], ""))

    parse(
        payload,
        runner,
        engine_root=Path("engine"),
        game_root=Path("game"),
        executable=Path("host.exe"),
        timeout_seconds=5.0,
    )

    call = runner.calls[0]
    assert call["engine_root"] == Path("engine")
    assert call["game_root"] == Path("game")
    assert call["executable"] == Path("host.exe")
    assert call["timeout_seconds"] == 5.0
    assert Path(call["environment"][IMPORT_TAC_ENVIRONMENT]).name == "tactic_stream.tac"
