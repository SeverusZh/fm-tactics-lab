"""Small FMF v8 archive writer; TAC payloads come from the game's serializer."""
import struct,time,uuid

HEADER=bytes.fromhex('0201666d662e080000')
TAC_CONTENT=bytes.fromhex('03016361742e2200')
ZSTD_MAGIC=bytes.fromhex('28b52ffd')
def string(value):
    raw=value.encode('utf8');return struct.pack('<I',len(raw))+raw
def zstd_raw(value):
    # A standard Zstandard frame made of raw blocks, requiring no third-party
    # compressor in the distributed private Python runtime.
    result=bytearray(ZSTD_MAGIC+b'\xa0'+struct.pack('<I',len(value)))
    for offset in range(0,max(1,len(value)),65536):
        block=value[offset:offset+65536];last=offset+len(block)>=len(value)
        result+=((len(block)<<3)|int(last)).to_bytes(3,'little')+block
    return bytes(result)
def tactics_archive(plan,title):
    content=TAC_CONTENT+plan
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

def _zstd_frame(value,start):
    if value[start:start+4]!=ZSTD_MAGIC:raise ValueError('战术归档缺少 Zstandard 数据')
    position=start+4
    if position>=len(value):raise ValueError('Zstandard 帧头不完整')
    descriptor=value[position];position+=1
    if descriptor&8:raise ValueError('Zstandard 帧头保留位无效')
    if descriptor&3:raise ValueError('Zstandard 帧不支持字典')
    single=descriptor>>5&1;flag=descriptor>>6&3;checksum=4 if descriptor&4 else 0
    if not single:position+=1
    size_bytes=1 if flag==0 and single else (0,2,4,8)[flag]
    if position+size_bytes>len(value):raise ValueError('Zstandard 帧头不完整')
    declared=int.from_bytes(value[position:position+size_bytes],'little')if size_bytes else None
    position+=size_bytes
    result=bytearray()
    while True:
        if position+3>len(value):raise ValueError('Zstandard 块头越过归档边界')
        header=int.from_bytes(value[position:position+3],'little');position+=3
        last=header&1;kind=header>>1&3;size=header>>3
        if kind==0:
            if position+size>len(value):raise ValueError('Zstandard 原始块越过归档边界')
            if declared is not None and len(result)+size>declared:raise ValueError('Zstandard 帧内容长度与声明不符')
            result+=value[position:position+size];position+=size
        elif kind==1:
            if position>=len(value):raise ValueError('Zstandard 重复块越过归档边界')
            if declared is not None and len(result)+size>declared:raise ValueError('Zstandard 帧内容长度与声明不符')
            result+=value[position:position+1]*size;position+=1
        else:raise ValueError('战术归档使用了未受支持的 Zstandard 压缩块')
        if last:break
    if declared is not None and len(result)!=declared:raise ValueError('Zstandard 帧内容长度与声明不符')
    if position+checksum>len(value):raise ValueError('Zstandard 校验和越过归档边界')
    return bytes(result),position+checksum

def _archive_string(value,position):
    if position+4>len(value):raise ValueError('战术归档目录已损坏')
    size=struct.unpack_from('<I',value,position)[0];position+=4
    if size>4096 or position+size>len(value):raise ValueError('战术归档目录已损坏')
    return value[position:position+size],position+size

def _archive_entry(value,position):
    name,position=_archive_string(value,position);extension,position=_archive_string(value,position)
    if position+40>len(value):raise ValueError('战术归档目录已损坏')
    offset,stored,raw,created,modified=struct.unpack_from('<QQQqq',value,position)
    return {'name':name,'extension':extension,'offset':offset,'stored':stored,'raw':raw},position+40

def tactics_plan(payload):
    # Extract the first .tac entry from an FMF v8 archive and return its raw plan.
    if not isinstance(payload,(bytes,bytearray,memoryview)):raise ValueError('战术归档必须是字节串')
    value=bytes(payload)
    if len(value)<len(HEADER)+17+len(HEADER)+3:raise ValueError('战术归档过短')
    if not value.startswith(HEADER):raise ValueError('战术归档文件头无效')
    total,second,revision=struct.unpack_from('<QQB',value,len(HEADER))
    if second!=17 or revision!=3 or total<17:raise ValueError('战术归档头字段无效')
    start=len(HEADER)+17;end=start+total-17
    if end+len(HEADER)>len(value):raise ValueError('战术归档长度越界')
    chunks=[];frames=[];position=start
    while position<end:
        before=position;chunk,position=_zstd_frame(value,position)
        if position>end:raise ValueError('战术数据块越过归档边界')
        chunks.append(chunk);frames.append(position-before)
    if position!=end or len(chunks)!=2:raise ValueError('战术归档文件数量或块边界无效')
    if value[end:end+len(HEADER)]!=HEADER:raise ValueError('战术归档缺少目录头')
    toc,toc_end=_zstd_frame(value,end+len(HEADER))
    if toc_end!=len(value):raise ValueError('战术归档尾部长度无效')
    title,position=_archive_string(toc,0)
    if position+4>len(toc):raise ValueError('战术归档目录已损坏')
    root_count=struct.unpack_from('<I',toc,position)[0];position+=4
    if root_count!=1:raise ValueError('战术归档根目录无效')
    tac,position=_archive_entry(toc,position)
    if position+4>len(toc):raise ValueError('战术归档目录已损坏')
    folder_count=struct.unpack_from('<I',toc,position)[0];position+=4
    if folder_count!=1:raise ValueError('战术归档目录数量无效')
    folder,position=_archive_string(toc,position)
    if position+4>len(toc):raise ValueError('战术归档目录已损坏')
    file_count=struct.unpack_from('<I',toc,position)[0];position+=4
    details,position=_archive_entry(toc,position)
    if position+4>len(toc):raise ValueError('战术归档目录已损坏')
    terminator=struct.unpack_from('<I',toc,position)[0];position+=4
    if terminator or position!=len(toc):raise ValueError('战术归档目录尾部无效')
    if file_count!=1 or folder!=b'_data' or tac['extension']!=b'.tac' or details['extension']!=b'.aom':
        raise ValueError('战术归档文件类型无效')
    if (tac['name']!=title or tac['offset'] or details['offset']!=frames[0] or
        tac['stored']!=frames[0] or details['stored']!=frames[1] or
        tac['raw']!=len(chunks[0]) or details['raw']!=len(chunks[1])):
        raise ValueError('战术归档目录与内容不一致')
    content=chunks[0]
    if not content.startswith(TAC_CONTENT):raise ValueError('内嵌内容不是 TAC 战术计划')
    return content[len(TAC_CONTENT):]

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
