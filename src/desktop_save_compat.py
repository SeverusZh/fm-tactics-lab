"""Observed FM27 save layouts; extends exact registrations, never disables checks.

Supported saves: 27.0.0+2486695, 27.0.0+2493426 and 27.0.1+2494687.
The two later builds use summary/game/humans/tactics schemas 31/47/24/26. Plan flag 2 also occurs
in native standalone FMF plans, and does not change the slot layout.
Nonempty counted secondary slot maps are walked without changing native bytes.
This adapter is installed only inside the private save-reader process.
"""
from dataclasses import replace

PROFILE = 'fm27-save-2486695-2494687-v7'
LATER_BUILDS = ('27.0.0+2493426', '27.0.1+2494687')
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
        for build in LATER_BUILDS:
            later=layout
            if isinstance(layout,TacticsLayout) and build=='27.0.1+2494687':
                # The TAC header stores 27.0.1 in the same field that held
                # 27.0.0. Revision 68 and the slot grammar remain unchanged.
                def signature(value):
                    return value[:5]+b'\x01'+value[6:]
                later=replace(layout,user_signature=signature(layout.user_signature),
                              preset_signature=signature(layout.preset_signature),
                              alternate_signature=signature(layout.alternate_signature))
            entries.append(replace(entry,build=build,layout=later))
    registered=tuple(entries)
    _layouts.registered_layouts=lambda:registered
    _install_slot_map_reader(tuple(e.layout for e in registered
                                  if isinstance(e.layout,TacticsLayout)
                                  and e.build in ('27.0.0+2486695', *LATER_BUILDS)))
    read_game_info_facts=_version.read_game_info_facts

    def read_registered_game_info(container, schemas, version, known_build):
        if version.build in LATER_BUILDS and schemas.get('game_info')==47:
            # The cross-build fallback sees two matches when the list is empty.
            # Select the observed build's layout and still check clock and tail.
            layout=_layouts.find_layout(GameInfoLayout,'game_info',47,version.build).layout
            data=_version.read_metadata_section(container,'game_info')
            return _version.checked_game_info_candidate(data,layout,version,container.file_name)
        return read_game_info_facts(container,schemas,version,known_build)

    _version.read_game_info_facts=read_registered_game_info
    _layouts._fm27_desktop_profile=PROFILE


def _install_slot_map_reader(layouts):
    """Walk the counted secondary map before the final eight-byte role flags.

    Native fm27_tactic_player_slot_read reads a uint32 count,
    then count * (uint32 key + uint64 value), after the setting entries.
    The dependency's fixed walk covers only the zero-count form. Keep its
    existing descriptive model and checks; raw native plans retain every map
    entry, and are the sole source of simulated instructions and role flags.
    """
    from fmsave.readers import tactics
    original=getattr(tactics._read_slot_block,'_fm27_original',tactics._read_slot_block)

    def read_slot(section,cursor,record_end,layout,*,with_index_byte):
        if layout not in layouts:
            return original(section,cursor,record_end,layout,with_index_byte=with_index_byte)
        header=len(layout.slot_tag)+4+len(layout.slot_constant)+4
        if cursor<0 or record_end>len(section) or cursor+header>record_end:
            return None
        count=int.from_bytes(section[cursor+header-4:cursor+header],'little')
        if not layout.unit_count_range[0]<=count<=layout.unit_count_range[1]:
            return None
        map_at=cursor+header+count*layout.unit_bytes
        fixed_end=map_at+4+8+int(with_index_byte)
        if fixed_end>record_end:
            return None
        extra=int.from_bytes(section[map_at:map_at+4],'little',signed=True)
        if extra<0 or extra>(record_end-fixed_end)//12:
            return None
        if not extra:
            return original(section,cursor,record_end,layout,with_index_byte=with_index_byte)
        map_end=map_at+4+extra*12
        block_end=fixed_end+extra*12
        # Normalize only this bounded slot for the legacy descriptive decoder;
        # never alter the saved raw plan handed to the native TAC reader.
        normalized=section[cursor:map_at+4]+section[map_end:block_end]
        slot=original(normalized,0,len(normalized),layout,with_index_byte=with_index_byte)
        if slot is None or slot.end!=len(normalized):
            return None
        return replace(slot,end=block_end)

    read_slot._fm27_original=original
    tactics._read_slot_block=read_slot
