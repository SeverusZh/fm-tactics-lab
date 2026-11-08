"""Small FMF v8 archive writer; TAC payloads come from the game's serializer."""
import struct,time,uuid

HEADER=bytes.fromhex('0201666d662e080000')
def string(value):
    raw=value.encode('utf8');return struct.pack('<I',len(raw))+raw
def zstd_raw(value):
    # A standard Zstandard frame made of raw blocks, requiring no third-party
    # compressor in the distributed private Python runtime.
    result=bytearray(bytes.fromhex('28b52ffda0')+struct.pack('<I',len(value)))
    for offset in range(0,max(1,len(value)),65536):
        block=value[offset:offset+65536];last=offset+len(block)>=len(value)
        result+=((len(block)<<3)|int(last)).to_bytes(3,'little')+block
    return bytes(result)
def tactics_archive(plan,title):
    content=bytes.fromhex('03016361742e2200')+plan
    # AOM v4: handler, title, description, empty attachment, flags, unpublished
    # workshop IDs, author and format/build metadata. No third-party identity.
    details=bytes.fromhex('03016d6f612e0400')+string('TACTICS_TYPE_HANDLER')+string(title)+string('FM27 tactics editor')+bytes(6)+bytes([255])*16+string('FM27 Tactics')+bytes.fromhex('020001000281490d03010010')+uuid.uuid4().bytes[:10]
    files=[(title,'.tac',content),('details','.aom',details)]
    chunks=[zstd_raw(item[2])for item in files];now=int(time.time())
    def entry(index,offset):
        name,ext,raw=files[index]
        return string(name)+string(ext)+struct.pack('<QQQqq',offset,len(chunks[index]),len(raw),now,now)
    toc=string(title)+struct.pack('<I',1)+entry(0,0)+struct.pack('<I',1)+string('_data')+struct.pack('<I',1)+entry(1,len(chunks[0]))+struct.pack('<I',0)
    payload=b''.join(chunks)
    return HEADER+struct.pack('<QQB',17+len(payload),17,3)+payload+HEADER+zstd_raw(toc)

SP_HANDLERS=['DEFEND_CORNER','DEFEND_FREE_KICK','DEFEND_ID_WIDE_FREE_KICK','DEFEND_ID_DEEP_FREE_KICK','DEFEND_LONG_THROW_IN','ATTACK_CORNER','ATTACK_FREE_KICK','ATTACK_ID_WIDE_FREE_KICK','ATTACK_ID_DEEP_FREE_KICK','THROW_IN']
SP_EXTENSIONS=['.dcspr','.dfkspr','.dfkspr','.dfkspr','.tispr','.acspr','.afkspr','.afkspr','.afkspr','.tispr']
def setpiece_archive(kind,routine):
    ext=SP_EXTENSIONS[kind];magic=(ext[1:4][::-1]+'.').encode('ascii');payload=bytearray(bytes([3,1])+magic+struct.pack('<H',60))
    for key in ['swing','strategy']:
        if routine[key]!=255:payload.append(routine[key])
    for group,values in enumerate(routine['groups']):payload+=bytes([group,len(values)]+values)
    payload+=bytes([len(routine['priority'])]+routine['priority'])
    backups=[(g,i,v)for g,values in enumerate(routine['backups'])for i,v in enumerate(values)if v]
    payload+=bytes([len(backups)])+b''.join(bytes(x)for x in backups)
    title=routine['name'];payload+=string(title)+bytes([routine['frequency']])+struct.pack('<I',0x4e554c4c)+bytes([routine.get('opaque_flags',0)])
    details=bytes.fromhex('03016d6f612e0400')+string(SP_HANDLERS[kind]+'_ROUTINE_TYPE_HANDLER')+string(title)+string('FM27 tactics editor')+bytes(6)+bytes([255])*16+string('FM27 Tactics')+bytes.fromhex('020001000281490d03010010')+uuid.uuid4().bytes[:10]
    chunks=[zstd_raw(bytes(payload)),zstd_raw(details)];now=int(time.time())
    def entry(name,extension,offset,stored,raw):return string(name)+string(extension)+struct.pack('<QQQqq',offset,stored,raw,now,now)
    toc=string(title)+struct.pack('<I',1)+entry(title,ext,0,len(chunks[0]),len(payload))+struct.pack('<I',1)+string('_data')+struct.pack('<I',1)+entry('details','.aom',len(chunks[0]),len(chunks[1]),len(details))+struct.pack('<I',0)
    body=b''.join(chunks);return HEADER+struct.pack('<QQB',17+len(body),17,3)+body+HEADER+zstd_raw(toc)
