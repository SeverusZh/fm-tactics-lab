"""FMF 战术文件编解码端口与 v2 文件格式说明。

v2 的 FMF 是工具自有归档，与 FM27 原生 FMF 不兼容：原生归档以 0x02 0x01
开头并封装游戏序列化块，写入与解析都依赖游戏进程；v2 文件由 ASCII 魔数
FMFV2、4 字节大端 JSON 长度和 UTF-8 JSON 场景文本组成，只保证场景内容在
不同入口之间确定地往返一致。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

FMF_MAGIC = b"FMFV2"
FMF_LENGTH_BYTES = 4


@runtime_checkable
class FmfCodec(Protocol):
    """战术 FMF 文件编解码边界。"""

    def encode(self, scenario: Mapping[str, Any]) -> bytes:
        """把场景归一化并编码为确定性的 v2 FMF 字节。"""
        ...

    def decode(self, data: bytes) -> Mapping[str, Any]:
        """校验 v2 FMF 字节并返回归一化场景，文件无效时抛出 ValueError。"""
        ...
