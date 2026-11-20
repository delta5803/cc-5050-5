"""核对：轮廓来源映射、度量（推进量）与整形结果（偏移量）的原版/子集一致性。"""
from __future__ import annotations

from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

from .hbshape import shape_text


def glyph_mapping(orig: TTFont, sub: TTFont) -> list[dict]:
    """按字形名称建立 子集新 gid -> 原版旧 gid 的映射。"""
    orig_gid = {n: i for i, n in enumerate(orig.getGlyphOrder())}
    out = []
    for new_gid, name in enumerate(sub.getGlyphOrder()):
        out.append({
            "new_gid": new_gid,
            "name": name,
            "old_gid": orig_gid.get(name),
        })
    return out


def _outline_ops(font: TTFont, name: str):
    glyph_set = font.getGlyphSet()
    pen = RecordingPen()
    glyph_set[name].draw(pen)
    return tuple(pen.value)


def compare_outlines(orig: TTFont, sub: TTFont) -> list[dict]:
    """逐字形比较轮廓（复合轮廓按各自字体解引用后比较绘制指令）。"""
    mismatches = []
    for name in sub.getGlyphOrder():
        if name not in orig.getGlyphOrder():
            mismatches.append({"name": name, "problem": "原版中不存在"})
            continue
        if _outline_ops(orig, name) != _outline_ops(sub, name):
            mismatches.append({"name": name, "problem": "轮廓指令不一致"})
    return mismatches


def compare_metrics(orig: TTFont, sub: TTFont) -> list[dict]:
    """逐字形比较 hmtx 推进量与左边界。"""
    mismatches = []
    oh, sh = orig["hmtx"], sub["hmtx"]
    for name in sub.getGlyphOrder():
        if name not in oh.metrics:
            mismatches.append({"name": name, "problem": "原版 hmtx 中不存在"})
            continue
        o_adv, o_lsb = oh.metrics[name]
        s_adv, s_lsb = sh.metrics[name]
        if (o_adv, o_lsb) != (s_adv, s_lsb):
            mismatches.append({
                "name": name,
                "problem": f"推进量/左边界 {s_adv},{s_lsb} != 原版 {o_adv},{o_lsb}",
            })
    return mismatches


def compare_shaping(orig_bytes: bytes, orig_order: list[str],
                    sub_bytes: bytes, sub_order: list[str],
                    text: str, features: dict, direction: str) -> dict:
    """比较同一段文本在原版与子集下的整形结果（字形名、推进量、偏移量）。"""
    a = shape_text(orig_bytes, orig_order, text, features, direction)
    b = shape_text(sub_bytes, sub_order, text, features, direction)
    diffs = []
    if len(a) != len(b):
        diffs.append(f"字形数量 {len(b)} != 原版 {len(a)}")
    for i, (ga, gb) in enumerate(zip(a, b)):
        if ga.key() != gb.key():
            diffs.append(
                f"位置 {i}: 子集 {gb.name} adv=({gb.x_advance},{gb.y_advance}) "
                f"off=({gb.x_offset},{gb.y_offset})，原版 {ga.name} "
                f"adv=({ga.x_advance},{ga.y_advance}) off=({ga.x_offset},{ga.y_offset})")
    return {"equal": not diffs, "diffs": diffs,
            "original": [g.name for g in a], "subset": [g.name for g in b]}
