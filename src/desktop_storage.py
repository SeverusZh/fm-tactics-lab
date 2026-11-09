"""Storage limits for rebuildable save research and desktop preparation."""
from pathlib import Path
import shutil

GIB = 1024**3
RESERVE_BYTES = 20 * GIB
SAVE_RESERVE_BYTES = 2 * GIB

def require_space(path, additional_bytes=0, *, reserve_bytes=RESERVE_BYTES):
    target = Path(path).resolve()
    p = target
    while not p.exists():p=p.parent
    free=shutil.disk_usage(p).free
    needed = reserve_bytes + additional_bytes
    if free < needed:
        raise ValueError(f'数据目录磁盘空间不足。{p.anchor} 剩余 {free/GIB:.1f} GiB，本操作需要 {needed/GIB:.1f} GiB。'
                         f'写入目录：{target}。可用 --data-dir 指定其他盘上的工具数据目录。')

def bounded_output(path,limit_bytes=256*1024**2):
    folder=Path(path)
    size=sum(p.stat().st_size for p in folder.rglob('*')if p.is_file())if folder.exists()else 0
    if size>limit_bytes:raise ValueError('本次准备目录超过256 MB上限，请先核查中间文件')
    require_space(folder, limit_bytes-size, reserve_bytes=SAVE_RESERVE_BYTES)
