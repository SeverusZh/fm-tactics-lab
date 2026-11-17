"""Player display identity from the game database and the save summary.

FM27 stores a player's registered shirt number in the contract chain of the game
database and the localized squad labels of the managed club in the save summary.
fmsave 0.12.4 exposes the layout lookup, contract decoder and player record index
needed to read them, but not as public API: every reader here fails closed and
returns an empty mapping, so a save whose layout differs only loses the optional
identity fields.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

# The registration layout and the summary offsets are confirmed against the
# saves these builds wrote; every other build keeps the historical fallback.
REGISTRATION_BUILDS = frozenset({"27.0.0+2486695", "27.0.1+2503222"})
GAME_DB_SCHEMA = 4000
SUMMARY_SCHEMA = 31
SUMMARY_CLUB_REFERENCE_OFFSET = 234
SUMMARY_MANAGER_REFERENCE_OFFSET = 542
SUMMARY_MIN_PLAYERS = 11
SUMMARY_MAX_PLAYERS = 100
MAX_SUMMARY_TEXT_BYTES = 512
SHIRT_MIN = 1
SHIRT_MAX = 99
UNASSIGNED_SHIRTS = frozenset({0, 255})
SHIRT_RECORD_OFFSET = 12
TEAM_ID_OFFSET = 9
SELECTOR_OFFSET = 5
_CJK = re.compile(r"[\u3400-\u9fff]")


def _fail_closed(read: Callable[[], dict[int, Any]]) -> dict[int, Any]:
    try:
        return read()
    except Exception:
        return {}


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError("摘要字段越界")
    return int.from_bytes(data[offset : offset + 4], "little")


def _summary_text(data: bytes, offset: int) -> tuple[str, int]:
    length = _u32(data, offset)
    start = offset + 4
    end = start + length
    if length > MAX_SUMMARY_TEXT_BYTES or end > len(data):
        raise ValueError("摘要字符串越界")
    return data[start:end].decode("utf-8"), end


def registered_shirts(save: Any, players: Sequence[Any]) -> dict[int, int | None]:
    """Return each player's registered shirt number keyed on unique_id.

    Only saves from the builds the layout was confirmed against, with game_db
    schema 4000, are read. A value is None when the in-force registration records
    disagree on one number or store an unassigned shirt; a player without a usable
    record is omitted instead of guessed.
    """
    return _fail_closed(lambda: _registered_shirts(save, players))


def _registered_shirts(save: Any, players: Sequence[Any]) -> dict[int, int | None]:
    from fmsave._layouts import ContractLayout, find_layout
    from fmsave.readers.contracts import build_contract_decoder
    from fmsave.readers.player_scan import window_end

    info = save.info
    if info.build not in REGISTRATION_BUILDS or info.section_schemas.get("game_db") != GAME_DB_SCHEMA:
        return {}
    context = save._context
    layout = find_layout(ContractLayout, "game_db", GAME_DB_SCHEMA, info.build).layout
    decoder = build_contract_decoder(layout, context.club_index(), info.game_date, info.file_name)
    if decoder.team_id_offset != TEAM_ID_OFFSET or decoder.selector_offset != SELECTOR_OFFSET:
        return {}
    records = context.player_records()
    selected = {player.uid: player for player in players}
    result: dict[int, int | None] = {}
    with context.section("game_db") as database:
        for index, uid in enumerate(records.uids):
            player = selected.get(uid)
            if player is None:
                continue
            start = records.record_offsets[index]
            end = window_end(records, index, len(database))
            chain = decoder._find_chain_records(
                database,
                start,
                end,
                index + 1 == len(records.uids),
                records.pindexes[index],
            )
            if not chain:
                continue
            numbers: set[int] = set()
            for tag_offset, record in zip(*chain, strict=True):
                club, _, team_id, _, began, expires, terms = record[:7]
                if (
                    club != player.club_uid
                    or began is None
                    or info.game_date is None
                    or began > info.game_date
                    or tag_offset - SHIRT_RECORD_OFFSET < start
                ):
                    continue
                if terms:
                    if expires is None or expires < info.game_date:
                        continue
                elif not (
                    player.on_loan is True
                    and team_id == player.team_id
                    and began == player.loan_start
                    and player.loan_end is not None
                    and info.game_date <= player.loan_end
                ):
                    continue
                value = int.from_bytes(
                    database[tag_offset - SHIRT_RECORD_OFFSET : tag_offset - SHIRT_RECORD_OFFSET + 2],
                    "little",
                )
                if value in UNASSIGNED_SHIRTS or SHIRT_MIN <= value <= SHIRT_MAX:
                    numbers.add(value)
            assigned = numbers - UNASSIGNED_SHIRTS
            if len(assigned) == 1:
                result[player.unique_id] = assigned.pop()
            elif numbers:
                result[player.unique_id] = None
    return {unique_id: number for unique_id, number in result.items() if unique_id is not None}


def summary_names(
    save: Any,
    players: Sequence[Any],
    shirts: Mapping[int, int | None],
) -> dict[int, str]:
    """Return localized squad labels from the save summary keyed on unique_id.

    The summary revision lists the first-team squad of every club with its
    registered numbers. A label is only taken when it joins exactly one player of
    the club whose registered number appears once in that list.
    """
    return _fail_closed(lambda: _summary_names(save, players, shirts))


def _summary_candidate(data: bytes, start: int) -> list[tuple[str, int]] | None:
    try:
        count = _u32(data, start)
    except ValueError:
        return None
    if not SUMMARY_MIN_PLAYERS <= count <= SUMMARY_MAX_PLAYERS:
        return None
    offset = start + 4
    try:
        labels: list[str] = []
        for _ in range(count):
            label, offset = _summary_text(data, offset)
            labels.append(label)
    except (UnicodeError, ValueError):
        return None
    try:
        trailer = _u32(data, offset)
    except ValueError:
        return None
    end = offset + 4 + count
    if trailer != count or end > len(data):
        return None
    return list(zip(labels, data[offset + 4 : end], strict=True))


def _summary_names(
    save: Any,
    players: Sequence[Any],
    shirts: Mapping[int, int | None],
) -> dict[int, str]:
    info = save.info
    if info.section_schemas.get("save_game_summary") != SUMMARY_SCHEMA:
        return {}
    clubs = sorted({player.club_uid for player in players if isinstance(player.club_uid, int)})
    if not clubs:
        return {}
    owners: dict[tuple[int, int], list[int]] = defaultdict(list)
    for player in players:
        if player.team_slot != 0 or player.unique_id is None:
            continue
        number = shirts.get(player.unique_id)
        if number is not None:
            owners[(player.club_uid, number)].append(player.unique_id)
    names: dict[int, str] = {}
    with save._context.section("save_game_summary") as data:
        for club_uid in clubs:
            marker = club_uid.to_bytes(4, "little")
            position = data.find(marker)
            while position >= 0:
                start = position + SUMMARY_CLUB_REFERENCE_OFFSET
                position = data.find(marker, position + 1)
                if start < SUMMARY_MANAGER_REFERENCE_OFFSET:
                    continue
                manager_reference = start - SUMMARY_MANAGER_REFERENCE_OFFSET
                if data[manager_reference : manager_reference + 4] != marker:
                    continue
                entries = _summary_candidate(data, start)
                if entries is None:
                    continue
                numbers = [number for _, number in entries]
                for label, number in entries:
                    identifiers = owners.get((club_uid, number), ())
                    if (
                        len(identifiers) == 1
                        and numbers.count(number) == 1
                        and _CJK.search(label)
                        and label.isprintable()
                    ):
                        names[identifiers[0]] = label
    return names
