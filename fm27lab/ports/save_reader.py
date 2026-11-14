"""Save reader port contract for the save library."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SaveReader(Protocol):
    """Read-only access to one Football Manager save file.

    Implementations never modify the source save and never leak reader objects:
    every method returns plain dictionaries and lists that the application layer
    can index, cache or serialize. Reading is bounded to the requested club; a
    full roster decode is not required to list clubs or one squad.
    """

    def read_info(self) -> dict[str, Any]:
        """Return save identity metadata.

        Keys: game, build, db_version, game_date (ISO 8601 date string or None)
        and save_name.
        """
        ...

    def read_managed_clubs(self) -> list[dict[str, Any]]:
        """Return the managed (human-controlled) clubs sorted by club_uid.

        Every item holds club_uid, club_name, club_short_name, manager_name and
        manager_staff_uid.
        """
        ...

    def read_clubs(self) -> list[dict[str, Any]]:
        """Return every club identity sorted by uid.

        Every item holds uid, unique_id, name, short_name and nation_id.
        """
        ...

    def read_squad(self, club_uid: int) -> list[dict[str, Any]]:
        """Return the players of one club sorted by source_uid.

        Every item holds source_uid (the save's player Unique ID, or a
        save-unique identifier when the save reports colliding ids; players
        that report no uid fall back to their unique id), name
        (players whose name is unreadable get the label 未知球员 <source_uid>),
        attributes (the 69 native attributes: indices 0-14 are position ratings
        and 15-68 hidden attributes), left_foot, right_foot, position (canonical
        position name), ability (current ability), age, height_cm and, when
        readable, personality (the seven editable personality attributes;
        unreadable entries are omitted).
        """
        ...

    def read_selection(self, club_uid: int) -> dict[str, Any] | None:
        """Return the club's stored current selection, or None when unreadable.

        Keys: club_uid, team_id, team_slot, lineup (starter source_uid values in
        tactic-slot order) and substitutes (substitute source_uid values in
        stored order).
        """
        ...


# The architecture documents name this port SaveReaderPort.
SaveReaderPort = SaveReader
