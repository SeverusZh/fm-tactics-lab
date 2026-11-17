"""Registered shirt number and save-summary display name parsing tests."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import fmsave._layouts
import fmsave.readers.contracts
import fmsave.readers.player_scan
import pytest

from fm27lab.adapters.save_fmsave.player_display import registered_shirts, summary_names

GAME_DATE = date(2028, 12, 26)
VERIFIED_BUILD = "27.0.1+2503222"
OTHER_BUILD = "27.0.2+9999999"
CLUB_UID = 741
CLUB_START = 100
CHAIN_TAG_OFFSET = 50


def make_info(
    *,
    build: str = VERIFIED_BUILD,
    game_db_schema: int = 4000,
    summary_schema: int = 31,
) -> SimpleNamespace:
    return SimpleNamespace(
        build=build,
        game_date=GAME_DATE,
        file_name="career.fm",
        section_schemas={"game_db": game_db_schema, "save_game_summary": summary_schema},
    )


class FakeSection:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> bytes:
        return self._data

    def __exit__(self, *exception: Any) -> bool:
        return False


class FakeContext:
    def __init__(
        self,
        *,
        game_db: bytes = b"",
        summary: bytes = b"",
        records: Any = None,
        failure: Exception | None = None,
    ) -> None:
        self.game_db = game_db
        self.summary = summary
        self.records = records
        self.failure = failure
        self.sections: list[str] = []

    def section(self, name: str) -> FakeSection:
        self.sections.append(name)
        if self.failure is not None:
            raise self.failure
        return FakeSection(self.game_db if name == "game_db" else self.summary)

    def club_index(self) -> object:
        return object()

    def player_records(self) -> Any:
        return self.records


class FakeSave:
    def __init__(
        self,
        *,
        info: SimpleNamespace | None = None,
        context: FakeContext | None = None,
        players: list[Any] | None = None,
    ) -> None:
        self.info = info if info is not None else make_info()
        self._context = context if context is not None else FakeContext()
        self._players = players or []

    def players(self) -> list[Any]:
        return self._players


class FakeContractDecoder:
    def __init__(self, chains: dict[int, tuple[list[int], list[tuple[Any, ...]]]]) -> None:
        self.team_id_offset = 9
        self.selector_offset = 5
        self.chains = chains
        self.calls = 0

    def _find_chain_records(
        self,
        database: bytes,
        start: int,
        end: int,
        is_last: bool,
        pindex: int,
    ) -> tuple[list[int], list[tuple[Any, ...]]] | None:
        self.calls += 1
        return self.chains.get(pindex)


def chain_record(
    *,
    club_uid: int = CLUB_UID,
    team_id: int = 100,
    began: date | None = date(2028, 7, 1),
    expires: date | None = date(2029, 6, 30),
    terms: bool = True,
) -> tuple[Any, ...]:
    return (club_uid, None, team_id, 1000, began, expires, terms, None, None, (), None, None)


def make_player(
    uid: int,
    *,
    unique_id: int | None = 5000,
    club_uid: int = CLUB_UID,
    team_slot: int = 0,
    team_id: int = 100,
    on_loan: bool | None = False,
    loan_start: date | None = None,
    loan_end: date | None = None,
    name: str = "Player",
) -> SimpleNamespace:
    return SimpleNamespace(
        uid=uid,
        unique_id=unique_id,
        club_uid=club_uid,
        team_slot=team_slot,
        team_id=team_id,
        on_loan=on_loan,
        loan_start=loan_start,
        loan_end=loan_end,
        name=name,
    )


def records_of(*starts: int) -> SimpleNamespace:
    return SimpleNamespace(
        uids=[index + 1 for index in range(len(starts))],
        record_offsets=list(starts),
        pindexes=[index + 1 for index in range(len(starts))],
    )


def install_internals(
    monkeypatch: pytest.MonkeyPatch,
    decoder: FakeContractDecoder,
) -> None:
    monkeypatch.setattr(fmsave._layouts, "ContractLayout", object)
    monkeypatch.setattr(
        fmsave._layouts,
        "find_layout",
        lambda *arguments: SimpleNamespace(layout=object()),
    )
    monkeypatch.setattr(
        fmsave.readers.contracts,
        "build_contract_decoder",
        lambda *arguments: decoder,
    )
    monkeypatch.setattr(
        fmsave.readers.player_scan,
        "window_end",
        lambda records, index, length: records.record_offsets[index] + 200,
    )


def game_db_with_shirts(*values: int, record_count: int) -> bytes:
    database = bytearray(CLUB_START + record_count * 300)
    for index, value in enumerate(values):
        tag_offset = CLUB_START + index * 300 + CHAIN_TAG_OFFSET
        database[tag_offset - 12 : tag_offset - 10] = value.to_bytes(2, "little")
    return bytes(database)


def summary_payload(
    club_uid: int,
    labels: list[str],
    numbers: bytes,
    *,
    count: int | None = None,
    label_length_override: int | None = None,
    manager_reference: bool = True,
) -> bytes:
    data = bytearray(4096)
    marker = club_uid.to_bytes(4, "little")
    data[234:238] = marker if manager_reference else b"\x00" * 4
    data[542:546] = marker
    start = 776
    declared = len(labels) if count is None else count
    data[start : start + 4] = declared.to_bytes(4, "little")
    offset = start + 4
    for index, label in enumerate(labels):
        encoded = label.encode("utf-8")
        length = declared if label_length_override is not None and index == 0 else len(encoded)
        data[offset : offset + 4] = length.to_bytes(4, "little")
        offset += 4
        if label_length_override is None or index != 0:
            data[offset : offset + len(encoded)] = encoded
            offset += len(encoded)
    data[offset : offset + 4] = len(labels).to_bytes(4, "little")
    offset += 4
    data[offset : offset + len(numbers)] = numbers
    return bytes(data)


def test_registered_shirts_reads_unique_assigned_number(monkeypatch: pytest.MonkeyPatch):
    player = make_player(11, unique_id=5001)
    assert player.uid == 11
    records = records_of(CLUB_START)
    records.uids = [11]
    decoder = FakeContractDecoder({1: ([CLUB_START + CHAIN_TAG_OFFSET], [chain_record()])})
    install_internals(monkeypatch, decoder)
    save = FakeSave(
        context=FakeContext(game_db=game_db_with_shirts(9, record_count=1), records=records),
        players=[player],
    )
    assert registered_shirts(save, [player]) == {5001: 9}


def test_registered_shirts_reports_ambiguous_numbers_as_none(monkeypatch: pytest.MonkeyPatch):
    first = CLUB_START + CHAIN_TAG_OFFSET
    second = CLUB_START + CHAIN_TAG_OFFSET + 20
    decoder = FakeContractDecoder({1: ([first, second], [chain_record(), chain_record()])})
    install_internals(monkeypatch, decoder)
    records = records_of(CLUB_START)
    records.uids = [11]
    database = bytearray(CLUB_START + 300)
    database[first - 12 : first - 10] = (7).to_bytes(2, "little")
    database[second - 12 : second - 10] = (8).to_bytes(2, "little")
    player = make_player(11, unique_id=5001)
    save = FakeSave(context=FakeContext(game_db=bytes(database), records=records), players=[player])
    assert registered_shirts(save, [player]) == {5001: None}


def test_registered_shirts_reports_unassigned_shirt_as_none(monkeypatch: pytest.MonkeyPatch):
    decoder = FakeContractDecoder({1: ([CLUB_START + CHAIN_TAG_OFFSET], [chain_record()])})
    install_internals(monkeypatch, decoder)
    records = records_of(CLUB_START)
    records.uids = [11]
    player = make_player(11, unique_id=5001)
    save = FakeSave(
        context=FakeContext(game_db=game_db_with_shirts(255, record_count=1), records=records),
        players=[player],
    )
    assert registered_shirts(save, [player]) == {5001: None}


def test_registered_shirts_ignores_expired_and_other_club_records(monkeypatch: pytest.MonkeyPatch):
    first = CLUB_START + CHAIN_TAG_OFFSET
    second = first + 20
    records = [
        chain_record(expires=date(2027, 6, 30)),
        chain_record(club_uid=CLUB_UID + 1),
    ]
    decoder = FakeContractDecoder({1: ([first, second], records)})
    install_internals(monkeypatch, decoder)
    player = make_player(11, unique_id=5001)
    player_records = records_of(CLUB_START)
    player_records.uids = [11]
    save = FakeSave(
        context=FakeContext(game_db=game_db_with_shirts(9, 99, record_count=2), records=player_records),
        players=[player],
    )
    assert registered_shirts(save, [player]) == {}


def test_registered_shirts_accepts_in_force_loan_registration(monkeypatch: pytest.MonkeyPatch):
    loan_start = date(2028, 7, 1)
    loan_end = date(2029, 6, 30)
    record = chain_record(began=loan_start, expires=None, terms=False)
    decoder = FakeContractDecoder({1: ([CLUB_START + CHAIN_TAG_OFFSET], [record])})
    install_internals(monkeypatch, decoder)
    player = make_player(
        11,
        unique_id=5001,
        on_loan=True,
        loan_start=loan_start,
        loan_end=loan_end,
    )
    player_records = records_of(CLUB_START)
    player_records.uids = [11]
    save = FakeSave(
        context=FakeContext(game_db=game_db_with_shirts(9, record_count=1), records=player_records),
        players=[player],
    )
    assert registered_shirts(save, [player]) == {5001: 9}


@pytest.mark.parametrize(
    "record",
    [
        chain_record(team_id=999, began=date(2028, 7, 1), expires=None, terms=False),
        chain_record(team_id=100, began=date(2028, 1, 1), expires=None, terms=False),
    ],
)
def test_registered_shirts_rejects_stale_loan_registration(
    monkeypatch: pytest.MonkeyPatch,
    record: tuple[Any, ...],
):
    loan_start = date(2028, 7, 1)
    loan_end = date(2029, 6, 30)
    decoder = FakeContractDecoder({1: ([CLUB_START + CHAIN_TAG_OFFSET], [record])})
    install_internals(monkeypatch, decoder)
    player = make_player(
        11,
        unique_id=5001,
        on_loan=True,
        loan_start=loan_start,
        loan_end=loan_end,
    )
    player_records = records_of(CLUB_START)
    player_records.uids = [11]
    save = FakeSave(
        context=FakeContext(game_db=game_db_with_shirts(9, record_count=1), records=player_records),
        players=[player],
    )
    assert registered_shirts(save, [player]) == {}


def test_registered_shirts_rejects_future_start(monkeypatch: pytest.MonkeyPatch):
    record = chain_record(began=date(2029, 1, 1), expires=date(2030, 6, 30))
    decoder = FakeContractDecoder({1: ([CLUB_START + CHAIN_TAG_OFFSET], [record])})
    install_internals(monkeypatch, decoder)
    player = make_player(11, unique_id=5001)
    player_records = records_of(CLUB_START)
    player_records.uids = [11]
    save = FakeSave(
        context=FakeContext(game_db=game_db_with_shirts(9, record_count=1), records=player_records),
        players=[player],
    )
    assert registered_shirts(save, [player]) == {}


@pytest.mark.parametrize(
    ("info", "reason"),
    [
        (make_info(build=OTHER_BUILD), "unverified build"),
        (make_info(game_db_schema=3999), "game_db schema"),
    ],
)
def test_registered_shirts_skips_unverified_layouts(
    monkeypatch: pytest.MonkeyPatch,
    info: SimpleNamespace,
    reason: str,
):
    decoder = FakeContractDecoder({1: ([CLUB_START + CHAIN_TAG_OFFSET], [chain_record()])})
    install_internals(monkeypatch, decoder)
    player = make_player(11, unique_id=5001)
    records = records_of(CLUB_START)
    records.uids = [11]
    save = FakeSave(
        info=info,
        context=FakeContext(game_db=game_db_with_shirts(9, record_count=1), records=records),
        players=[player],
    )
    assert registered_shirts(save, [player]) == {}, reason
    assert decoder.calls == 0


def test_registered_shirts_skips_unexpected_decoder_offsets(monkeypatch: pytest.MonkeyPatch):
    decoder = FakeContractDecoder({1: ([CLUB_START + CHAIN_TAG_OFFSET], [chain_record()])})
    decoder.team_id_offset = 8
    install_internals(monkeypatch, decoder)
    player = make_player(11, unique_id=5001)
    records = records_of(CLUB_START)
    records.uids = [11]
    save = FakeSave(
        context=FakeContext(game_db=game_db_with_shirts(9, record_count=1), records=records),
        players=[player],
    )
    assert registered_shirts(save, [player]) == {}
    assert decoder.calls == 0


def test_registered_shirts_fails_closed_on_unreadable_section(monkeypatch: pytest.MonkeyPatch):
    decoder = FakeContractDecoder({1: ([], [])})
    install_internals(monkeypatch, decoder)
    player = make_player(11)
    save = FakeSave(
        context=FakeContext(records=records_of(CLUB_START), failure=RuntimeError("损坏")),
        players=[player],
    )
    assert registered_shirts(save, [player]) == {}


def test_summary_names_joins_labels_to_registered_numbers(monkeypatch: pytest.MonkeyPatch):
    labels = [f"球员{index}" for index in range(1, 12)]
    numbers = bytes(range(1, 12))
    players = [make_player(100 + index, unique_id=5000 + index, team_slot=0) for index in range(11)]
    shirts = {player.unique_id: index for index, player in enumerate(players, start=1)}
    save = FakeSave(context=FakeContext(summary=summary_payload(CLUB_UID, labels, numbers)), players=players)
    names = summary_names(save, players, shirts)
    assert names == {player.unique_id: label for player, label in zip(players, labels, strict=True)}


def test_summary_names_requires_one_owner_per_number(monkeypatch: pytest.MonkeyPatch):
    labels = [f"球员{index}" for index in range(1, 12)]
    numbers = bytes(range(1, 12))
    first = make_player(100, unique_id=5000, team_slot=0)
    second = make_player(101, unique_id=5001, team_slot=0)
    players = [first, second]
    shirts = {5000: 1, 5001: 1}
    save = FakeSave(context=FakeContext(summary=summary_payload(CLUB_UID, labels, numbers)), players=players)
    assert summary_names(save, players, shirts) == {}


def test_summary_names_requires_unique_number_in_summary(monkeypatch: pytest.MonkeyPatch):
    labels = [f"球员{index}" for index in range(1, 13)]
    numbers = bytes([1, 2, 2, *range(4, 14)])
    players = [make_player(100 + index, unique_id=5000 + index, team_slot=0) for index in range(12)]
    shirts = {player.unique_id: index for index, player in enumerate(players, start=1)}
    save = FakeSave(context=FakeContext(summary=summary_payload(CLUB_UID, labels, numbers)), players=players)
    names = summary_names(save, players, shirts)
    assert 5001 not in names
    assert names[5003] == "球员4"


def test_summary_names_ignores_non_cjk_and_bench_players(monkeypatch: pytest.MonkeyPatch):
    labels = ["Saka", "球员2", *[f"球员{index}" for index in range(3, 12)]]
    numbers = bytes(range(1, 12))
    starter = make_player(100, unique_id=5000, team_slot=0)
    bench = make_player(101, unique_id=5001, team_slot=1)
    players = [starter, bench]
    shirts = {5000: 1, 5001: 2}
    save = FakeSave(context=FakeContext(summary=summary_payload(CLUB_UID, labels, numbers)), players=players)
    assert summary_names(save, players, shirts) == {}


def test_summary_names_skips_schema_mismatch(monkeypatch: pytest.MonkeyPatch):
    labels = [f"球员{index}" for index in range(1, 12)]
    players = [make_player(100 + index, unique_id=5000 + index) for index in range(11)]
    shirts = {player.unique_id: index for index, player in enumerate(players, start=1)}
    save = FakeSave(
        info=make_info(summary_schema=30),
        context=FakeContext(summary=summary_payload(CLUB_UID, labels, bytes(range(1, 12)))),
        players=players,
    )
    assert summary_names(save, players, shirts) == {}


def test_summary_names_skips_missing_manager_reference(monkeypatch: pytest.MonkeyPatch):
    labels = [f"球员{index}" for index in range(1, 12)]
    players = [make_player(100 + index, unique_id=5000 + index) for index in range(11)]
    shirts = {player.unique_id: index for index, player in enumerate(players, start=1)}
    save = FakeSave(
        context=FakeContext(
            summary=summary_payload(
                CLUB_UID,
                labels,
                bytes(range(1, 12)),
                manager_reference=False,
            )
        ),
        players=players,
    )
    assert summary_names(save, players, shirts) == {}


@pytest.mark.parametrize("player_count", [5, 101])
def test_summary_names_skips_out_of_range_player_count(
    monkeypatch: pytest.MonkeyPatch,
    player_count: int,
):
    labels = [f"球员{index}" for index in range(1, player_count + 1)]
    players = [
        make_player(100 + index, unique_id=5000 + index) for index in range(player_count)
    ]
    shirts = {player.unique_id: index for index, player in enumerate(players, start=1)}
    save = FakeSave(
        context=FakeContext(
            summary=summary_payload(CLUB_UID, labels, bytes(range(1, player_count + 1)))
        ),
        players=players,
    )
    assert summary_names(save, players, shirts) == {}


def test_summary_names_fails_closed_on_truncated_labels(monkeypatch: pytest.MonkeyPatch):
    player = make_player(100, unique_id=5000)
    summary = summary_payload(
        CLUB_UID,
        [f"球员{index}" for index in range(1, 12)],
        bytes(range(1, 12)),
        label_length_override=10_000,
    )
    save = FakeSave(context=FakeContext(summary=summary), players=[player])
    assert summary_names(save, [player], {5000: 1}) == {}


def test_summary_names_fails_closed_on_unreadable_section():
    player = make_player(100, unique_id=5000)
    save = FakeSave(context=FakeContext(failure=RuntimeError("损坏")), players=[player])
    assert summary_names(save, [player], {5000: 1}) == {}


def test_summary_names_without_players_returns_empty():
    save = FakeSave()
    assert summary_names(save, [], {}) == {}
