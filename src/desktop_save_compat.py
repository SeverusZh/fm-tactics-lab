"""Observed FM27 save layouts; extends exact registrations, never disables checks.

Validated saves: 27.0.0+2486695 and 27.0.0+2493426. The latter keeps
summary/game/humans/tactics schemas 31/47/24/26. Plan flag 2 also occurs
in native standalone FMF plans, and does not change the slot layout.
This adapter is installed only inside the private save-reader process.
"""
from dataclasses import replace

PROFILE = 'fm27-save-2486695-2493426-v5'
FRAME_DECOMPRESSED_CAP = 768 * 1024**2
TOTAL_DECOMPRESSED_CAP = 1536 * 1024**2


def install():
    from fmsave import _layouts, _version
    from fmsave._layouts import GameInfoLayout, TacticsLayout
    if getattr(_layouts,'_fm27_desktop_profile',None)==PROFILE:
        return
    _version.FM27_FRAME_DECOMPRESSED_CAP = FRAME_DECOMPRESSED_CAP
    _version.FM27_TOTAL_DECOMPRESSED_CAP = TOTAL_DECOMPRESSED_CAP
    original=_layouts.registered_layouts()
    entries=[]
    for entry in original:
        if entry.build!='27.0.0+2486695':
            entries.append(entry)
            continue
        layout=entry.layout
        if isinstance(layout,TacticsLayout):
            # Keep user flag 0 and preset flag 1; add the observed user flag 2.
            # Named routines share the length-prefixed name field used in FM26.
            layout=replace(layout,alternate_signature=layout.user_signature[:-1]+b'\x02',
                           named_routines_supported=True)
        entries.append(replace(entry,layout=layout))
        if isinstance(layout,GameInfoLayout) and entry.schema==47:
            # Schema 47 in this build places the filename count two bytes later.
            # Empty lists hid the offset error in earlier samples.
            layout=replace(layout,filename_count_offset_after_db_version=167)
        entries.append(replace(entry,build='27.0.0+2493426',layout=layout))
    registered=tuple(entries)
    _layouts.registered_layouts=lambda:registered
    read_game_info_facts=_version.read_game_info_facts

    def read_registered_game_info(container, schemas, version, known_build):
        if version.build=='27.0.0+2493426' and schemas.get('game_info')==47:
            # The cross-build fallback sees two matches when the list is empty.
            # Select the observed build's layout and still check clock and tail.
            layout=_layouts.find_layout(GameInfoLayout,'game_info',47,version.build).layout
            data=_version.read_metadata_section(container,'game_info')
            return _version.checked_game_info_candidate(data,layout,version,container.file_name)
        return read_game_info_facts(container,schemas,version,known_build)

    _version.read_game_info_facts=read_registered_game_info
    _layouts._fm27_desktop_profile=PROFILE
