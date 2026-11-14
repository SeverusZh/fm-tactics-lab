"""路径文本清洗：去掉资源管理器复制地址时附带的外层引号与首尾空白。"""

from __future__ import annotations

_QUOTE_CHARS = frozenset({'"', "'"})


def clean_path_text(value: object) -> str | None:
    """清洗路径文本；非字符串或清洗后为空时返回 None。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in _QUOTE_CHARS:
        text = text[1:-1].strip()
    return text or None
