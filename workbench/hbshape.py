"""HarfBuzz 整形封装：独立的整形路径，不经过任何系统字体栈。"""
from __future__ import annotations

from dataclasses import dataclass

import uharfbuzz as hb


@dataclass
class ShapedGlyph:
    gid: int
    name: str
    cluster: int
    x_advance: int
    y_advance: int
    x_offset: int
    y_offset: int

    def key(self):
        return (self.name, self.x_advance, self.y_advance, self.x_offset, self.y_offset)


def shape_text(font_bytes: bytes, glyph_order: list[str], text: str,
               features: dict[str, bool] | None = None,
               direction: str = "auto") -> list[ShapedGlyph]:
    """用给定字体文件字节整形一段文本，返回字形序列及定位信息。

    direction: "auto"（按内容猜测）/ "ltr" / "rtl"。
    features: 显式开关，如 {"liga": True, "kern": False}。
    """
    face = hb.Face(font_bytes)
    font = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    if direction in ("ltr", "rtl"):
        buf.direction = direction
    hb.shape(font, buf, features or {})
    out = []
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        gid = info.codepoint
        name = glyph_order[gid] if 0 <= gid < len(glyph_order) else f"gid{gid}"
        out.append(ShapedGlyph(
            gid=gid, name=name, cluster=info.cluster,
            x_advance=pos.x_advance, y_advance=pos.y_advance,
            x_offset=pos.x_offset, y_offset=pos.y_offset,
        ))
    return out


# 由 HarfBuzz 各文字整形器按阶段自动管理的特性：显式全局开启会覆盖
# 整形器的逐字形掩码（例如对阿拉伯文显式开 fina 会让所有字母都变成词尾形）。
# 因此启用时不在用户特性里传递（交给整形器），只有禁用才显式传 False。
SHAPER_MANAGED = {
    "isol", "init", "medi", "med2", "fina", "fin2", "fin3",
    "rlig", "calt", "cswh", "rclt",
}


def feature_switches(all_tags: list[str], enabled: set[str]) -> dict[str, bool]:
    """生成传给 HarfBuzz 的开关表：未启用的特性显式关闭。"""
    out = {}
    for tag in all_tags:
        if tag in SHAPER_MANAGED:
            if tag not in enabled:
                out[tag] = False
        else:
            out[tag] = tag in enabled
    return out
