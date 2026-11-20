"""子集打包：用 fontTools 把显式字形集合写成真实字体文件（TTF / WOFF2）。

layout_closure 关闭——闭包由 closure.ClosureTracer 显式计算，
保证"实测裁剪"方案不会被 fontTools 悄悄放大，也让闭包方案的结果可解释。
"""
from __future__ import annotations

import os

from fontTools import subset
from fontTools.ttLib import TTFont


def build_subset(font_path: str, glyphs: set[str], features: list[str],
                 out_path: str, flavor: str | None = None) -> int:
    options = subset.Options()
    options.name_IDs = ["*"]          # 保留许可信息等全部 name 记录
    options.layout_features = list(features)
    options.layout_closure = False    # 闭包已由调用方计算
    options.glyph_names = True        # 保留 post 名称，便于轮廓来源映射核对
    options.notdef_outline = True
    options.recalc_timestamp = False  # 可复现的字节输出
    options.recalc_average_width = True

    font = TTFont(font_path)
    subsetter = subset.Subsetter(options)
    subsetter.populate(glyphs=sorted(glyphs))
    subsetter.subset(font)
    if flavor:
        font.flavor = flavor
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    font.save(out_path)
    font.close()
    return os.path.getsize(out_path)


def build_ttf_and_woff2(font_path: str, glyphs: set[str], features: list[str],
                        out_base: str) -> dict[str, int]:
    """out_base 不含扩展名；返回 {"ttf": bytes, "woff2": bytes}。"""
    sizes = {}
    sizes["ttf"] = build_subset(font_path, glyphs, features, out_base + ".ttf")
    sizes["woff2"] = build_subset(font_path, glyphs, features,
                                  out_base + ".woff2", flavor="woff2")
    return sizes
