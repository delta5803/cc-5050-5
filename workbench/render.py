"""独立绘制路径：把整形结果用 fontTools 轮廓笔画成 SVG，不经过系统字体栈。

缺字时画出 .notdef（豆腐块），即"关闭系统字体回退"的直接体现。
"""
from __future__ import annotations

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

from .hbshape import ShapedGlyph


def _glyph_path(font: TTFont, glyph_set, name: str) -> str:
    pen = SVGPathPen(glyph_set)
    try:
        glyph_set[name].draw(pen)
    except Exception:
        return ""
    return pen.getCommands()


def render_shaped_svg(font: TTFont, shaped: list[ShapedGlyph],
                      px_per_em: int = 40, mark_notdef: bool = True,
                      show_boxes: bool = False) -> str:
    """把一串整形后的字形渲染成 SVG 字符串。坐标为字体单位，y 向上。"""
    glyph_set = font.getGlyphSet()
    head = font["head"]
    hhea = font["hhea"]
    upem = head.unitsPerEm
    asc, desc = hhea.ascent, hhea.descent

    x = 0
    parts = []
    boxes = []
    for g in shaped:
        d = _glyph_path(font, glyph_set, g.name)
        fill = ' class="notdef"' if (mark_notdef and g.name == ".notdef") else ""
        tx, ty = x + g.x_offset, g.y_offset
        if d:
            parts.append(f'<path d="{d}" transform="translate({tx} {ty})"{fill}/>')
        if show_boxes:
            boxes.append(
                f'<rect class="adv" x="{x}" y="{desc}" width="{g.x_advance}" '
                f'height="{asc - desc}"/>')
        x += g.x_advance

    width = max(x, 1)
    height = asc - desc
    scale = px_per_em / upem
    w_px = round(width * scale, 1)
    h_px = round(height * scale, 1)
    baseline = asc
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{w_px}" height="{h_px}" class="render">',
        f'<g transform="translate(0 {asc}) scale(1 -1)">',
        *parts,
        '</g>',
        f'<line class="baseline" x1="0" y1="{baseline}" x2="{width}" y2="{baseline}"/>',
        *boxes,
        '</svg>',
    ]
    return "".join(svg)


def render_glyph_svg(font: TTFont, name: str, px: int = 96) -> str:
    """单个字形的小图，用于字形清单与检查器。"""
    glyph_set = font.getGlyphSet()
    head = font["head"]
    hhea = font["hhea"]
    upem = head.unitsPerEm
    asc, desc = hhea.ascent, hhea.descent
    adv = font["hmtx"].metrics.get(name, (upem // 2, 0))[0]
    d = _glyph_path(font, glyph_set, name)
    width = max(adv, 1)
    height = asc - desc
    scale = px / upem
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{round(width * scale, 1)}" height="{round(height * scale, 1)}" '
        f'class="glyphcell"><g transform="translate(0 {asc}) scale(1 -1)">'
        f'<path d="{d}"/></g></svg>'
    )
