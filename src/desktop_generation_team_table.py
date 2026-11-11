"""Counted TEAM table grammar from current native 11dfca0 + 117bcc0.

The complete ordinal/footer walk must succeed. A matching partial prefix is
never returned as a recovered table.
"""
import re,struct
U32=struct.Struct('<I');U16=struct.Struct('<H');FOOT=struct.Struct('<III')

def record(data,at,ordinal):
    start=at
    if at+54>len(data)or data[at]>11:return None
    variant=data[at];at+=1
    if variant==11:
        if at+54>len(data):return None
        extra=data[at+53]
        if extra>127:return None
        at+=54+10*extra
    body=at
    reputation=U16.unpack_from(data,at+2)[0]
    if reputation>10000:return None
    n=U16.unpack_from(data,at+33)[0]
    if n>4096:return None
    at+=53+4*n
    if at+10>len(data):return None
    base=at
    kind,slot=data[at:at+2]
    if kind>80 or slot>30:return None
    club=U32.unpack_from(data,at+6)[0]
    at+=10;names=[]
    for trailing in (1,1):
        if at+4>len(data):return None
        size=U32.unpack_from(data,at)[0];at+=4
        if size>4096 or at+size+trailing>len(data):return None
        try:name=data[at:at+size].decode('utf8')
        except UnicodeDecodeError:return None
        if '\0'in name:return None
        names.append(name);at+=size+trailing
    if at+12>len(data):return None
    index,uid,copy=FOOT.unpack_from(data,at)
    # The original reader retains two identity words without requiring equality;
    # career-allocated TEAMs can differ. Preserve both, never normalize them.
    if index!=ordinal or uid==0xffffffff or copy==0xffffffff:return None
    return {'team_id':index,'unique_id':uid,'uid_copy':copy,'variant':variant,'kind':kind,'slot':slot,
        'stored_club_index':club,'name':names[0],'short_name':names[1],
        'source_offset':start,'source_end':at+12,'body_offset':body,'base_offset':base,
        'native_reputation':reputation,'coach_person_reference':U32.unpack_from(data,body+20)[0],
        'field_78_reference':U32.unpack_from(data,body+16)[0],
        'captain_person_reference':U32.unpack_from(data,body+35+4*n)[0],
        'vice_captain_person_reference':U32.unpack_from(data,body+39+4*n)[0],
        'body_fixed_prefix_hex':data[body:body+35].hex(),'member_references':list(struct.unpack_from('<'+str(n)+'I',data,body+35))}

def locate(data,count,wanted=None):
    assert 0<count<1000000
    needle=U32.pack(count);candidates=[];at=0;attempts=[]
    while True:
        hit=data.find(needle,at)
        if hit<0:break
        at=hit+1
        if hit+5>=len(data)or data[hit+4]>3:continue
        cursor=hit+5;rows=[]
        for index in range(count):
            r=record(data,cursor,index)
            if r is None:break
            cursor=r['source_end']
            if wanted is None or index in wanted:rows.append(r)
        else:
            candidates.append({'count':count,'header_offset':hit,'end':cursor,'records':rows})
        attempts.append({'offset':hit,'accepted_records':index+(r is not None),'failure_offset':cursor})
    if len(candidates)!=1:raise ValueError({'error':'TEAM table not uniquely verified','candidates':len(candidates),'attempts':attempts})
    return candidates[0]


def from_save(save,data,wanted=None):
    """Use the club index as a lower bound, not the complete TEAM count.

    Career-created/non-club teams can follow the last club-listed team. Try the
    indexed count first, then discover a declared count with the same full walk.
    Every ordinal/footer must still pass and exactly one table must qualify.
    """
    index=save._context.club_index().team_to_club
    if not index:raise ValueError('Empty source team index')
    minimum=max(index)+1
    try:return locate(data,minimum,wanted)
    except ValueError as error:
        if not isinstance(error.args[0],dict)or error.args[0].get('candidates')!=0:raise
    return discover(data,minimum,wanted)


def discover(data,minimum,wanted=None):
    """Find candidate count words; only a complete unique table is returned."""
    assert 0<minimum<1000000
    # Overlapping lookahead avoids skipping a real header next to a false hit.
    # Same count cap, mode byte and first-record variant as locate().
    pattern=re.compile(rb'(?=(.{2}[\x00-\x0f]\x00)[\x00-\x03][\x00-\x0b])',re.DOTALL)
    candidates=[];attempts=[]
    for match in pattern.finditer(data):
        hit=match.start();count=U32.unpack_from(data,hit)[0]
        if not minimum<=count<1000000:continue
        first=record(data,hit+5,0)
        if first is None:continue
        if count>1 and record(data,first['source_end'],1)is None:continue
        cursor=hit+5;rows=[]
        for ordinal in range(count):
            row=record(data,cursor,ordinal)
            if row is None:break
            cursor=row['source_end']
            if wanted is None or ordinal in wanted:rows.append(row)
        else:
            candidates.append({'count':count,'header_offset':hit,'end':cursor,'records':rows})
        if len(attempts)<16:
            attempts.append({'offset':hit,'count':count,'accepted_records':ordinal+(row is not None),'failure_offset':cursor})
    if len(candidates)!=1:
        raise ValueError({'error':'TEAM table not uniquely verified','minimum_count':minimum,
                          'candidates':len(candidates),'attempts':attempts})
    return candidates[0]

if __name__=='__main__':
    import sys,json
    from pathlib import Path
    from desktop_generation_inputs import export
    import desktop_save_compat
    desktop_save_compat.install()
    import fmsave
    from fmsave import _version
    _version.FM27_FRAME_DECOMPRESSED_CAP=768*1024**2;_version.FM27_TOTAL_DECOMPRESSED_CAP=1536*1024**2
    folder=Path(sys.argv[1]);d=json.loads((folder/'generation_inputs.json').read_text(encoding='utf8'))
    complete=[]
    for line in (folder/'manager_native_100000.jsonl').read_text(encoding='utf8').splitlines():
        try:e=json.loads(line)
        except ValueError:continue
        if e.get('event')=='manager_diagnostic_complete':complete.append(e)
    assert len(complete)==1 and complete[0]['offset']==complete[0]['size']
    wanted={t['team_id']for c in d['clubs']for t in c['teams']if t['slot']==0}
    with fmsave.open(d['source'])as save:
        with save._context.section('game_db')as db:
            result=locate(db,complete[0]['records'],wanted)
            raw=bytes(db[result['header_offset']:result['end']])
            (folder/'team_table.bin').write_bytes(raw)
    import hashlib
    result['table_sha256']=hashlib.sha256(raw).hexdigest()
    result['source_sha256']=d['source_sha256']
    (folder/'source_team_table.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
