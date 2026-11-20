"""编排：一次构建产出两种裁剪方案的候选子集、核对结果与冲突分析。"""
from __future__ import annotations

import hashlib
import json
import os

from fontTools.ttLib import TTFont

from .closure import (ClosureTracer, Reason, collect_positioning,
                      reverse_input_closure)
from .conflict import analyze_conflict
from .hbshape import feature_switches, shape_text
from .render import render_shaped_svg
from .subsetter import build_subset, build_ttf_and_woff2
from .verify import (compare_metrics, compare_outlines, compare_shaping,
                     glyph_mapping)

OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "out")


def _shaped_strategy_glyphs(font, font_bytes, order, corpus, switches, direction):
    """方案 A：语料字符的 cmap 字形 + 训练语料实测整形产出的字形。"""
    glyphs = {".notdef"}
    reasons = {
        ".notdef": Reason("root", None, None, "缺省字形 .notdef"),
    }
    cmap = font.getBestCmap()
    for text in corpus:
        for ch in text:
            name = cmap.get(ord(ch))
            if name and name not in glyphs:
                glyphs.add(name)
                reasons[name] = Reason(
                    "cmap", None, None, f"语料字符 U+{ord(ch):04X} {ch}")
    for text in corpus:
        for g in shape_text(font_bytes, order, text, switches, direction):
            if g.name not in glyphs:
                glyphs.add(g.name)
                reasons[g.name] = Reason(
                    "gsub", None, None,
                    f"样本「{text}」实测整形产出")
    return glyphs, reasons


def _add_composite_reasons(font, glyphs, reasons):
    """复合轮廓组件也必须留下（轮廓完整性），补充原因记录。"""
    if "glyf" not in font:
        return
    glyf = font["glyf"]
    changed = True
    while changed:
        changed = False
        for name in list(glyphs):
            g = glyf[name]
            if g.isComposite():
                for comp in g.components:
                    if comp.glyphName not in glyphs:
                        glyphs.add(comp.glyphName)
                        reasons[comp.glyphName] = Reason(
                            "composite", None, None,
                            f"复合轮廓 {name} 引用的组件", (name,))
                        changed = True


def _closure_strategy_glyphs(font, corpus, features):
    """方案 B：沿启用的布局规则求依赖闭包。"""
    tracer = ClosureTracer(font, features)
    tracer.seed_samples(corpus)
    tracer.run()
    tracer.annotate_positioning()
    return tracer


def _verify_strategy(orig_font, orig_bytes, orig_order, sub_path, sub_bytes,
                     samples, switches, direction):
    sub_font = TTFont(sub_path)
    sub_order = sub_font.getGlyphOrder()
    mapping = glyph_mapping(orig_font, sub_font)
    mapping_ok = all(m["old_gid"] is not None for m in mapping)
    outlines = compare_outlines(orig_font, sub_font)
    metrics = compare_metrics(orig_font, sub_font)
    sample_checks = []
    for text in samples:
        check = compare_shaping(orig_bytes, orig_order, sub_bytes, sub_order,
                                text, switches, direction)
        sample_checks.append({"text": text, **check})
    sub_font.close()
    return {
        "mapping": mapping,
        "mapping_ok": mapping_ok,
        "outline_mismatches": outlines,
        "metric_mismatches": metrics,
        "sample_checks": sample_checks,
    }


def build(font_path: str, features: list[str], direction: str,
          corpus: list[str], heldout: list[str],
          size_limit: int | None, out_root: str = OUT_ROOT) -> dict:
    font_bytes = open(font_path, "rb").read()
    font = TTFont(font_path)
    order = font.getGlyphOrder()
    orig_num_glyphs = font["maxp"].numGlyphs

    all_tags = set()
    for tag in ("GSUB", "GPOS"):
        if tag in font:
            all_tags.update(r.FeatureTag for r in
                            font[tag].table.FeatureList.FeatureRecord)
    enabled = set(features)
    switches = feature_switches(sorted(all_tags), enabled)

    all_samples = list(corpus) + list(heldout)

    build_id = hashlib.sha1(json.dumps({
        "font": font_path, "features": sorted(enabled), "direction": direction,
        "corpus": corpus, "heldout": heldout, "limit": size_limit,
        "font_sha": hashlib.sha1(font_bytes).hexdigest(),
    }, sort_keys=True).encode()).hexdigest()[:12]
    build_dir = os.path.join(out_root, build_id)
    os.makedirs(build_dir, exist_ok=True)

    # ---- 方案 A：实测字形裁剪 ----
    shaped_glyphs, shaped_reasons = _shaped_strategy_glyphs(
        font, font_bytes, order, corpus, switches, direction)
    # 补齐整形中间阶段的输入字形（如 lam-alef 连字的词形输入）
    shaped_glyphs = reverse_input_closure(font, enabled, shaped_glyphs,
                                          shaped_reasons)
    _add_composite_reasons(font, shaped_glyphs, shaped_reasons)
    shaped_pos = collect_positioning(font, enabled, shaped_glyphs)
    shaped_sizes = build_ttf_and_woff2(
        font_path, shaped_glyphs, sorted(enabled),
        os.path.join(build_dir, "shaped"))

    # ---- 方案 B：依赖闭包 ----
    tracer = _closure_strategy_glyphs(font, corpus, enabled)
    closure_glyphs = set(tracer.glyphs)
    degenerate = len(closure_glyphs) >= orig_num_glyphs
    closure_sizes = build_ttf_and_woff2(
        font_path, closure_glyphs, sorted(enabled),
        os.path.join(build_dir, "closure"))

    # ---- 核对 ----
    shaped_bytes = open(os.path.join(build_dir, "shaped.ttf"), "rb").read()
    closure_bytes = open(os.path.join(build_dir, "closure.ttf"), "rb").read()
    verify_shaped = _verify_strategy(font, font_bytes, order,
                                     os.path.join(build_dir, "shaped.ttf"),
                                     shaped_bytes, all_samples, switches,
                                     direction)
    verify_closure = _verify_strategy(font, font_bytes, order,
                                      os.path.join(build_dir, "closure.ttf"),
                                      closure_bytes, all_samples, switches,
                                      direction)

    # ---- 渲染（独立整形 + 绘制路径）----
    sub_shaped_font = TTFont(os.path.join(build_dir, "shaped.ttf"))
    sub_closure_font = TTFont(os.path.join(build_dir, "closure.ttf"))
    sub_shaped_order = sub_shaped_font.getGlyphOrder()
    sub_closure_order = sub_closure_font.getGlyphOrder()

    def render_set(font_obj, font_ord, font_bytes_):
        out = []
        for text in all_samples:
            shaped = shape_text(font_bytes_, font_ord, text, switches, direction)
            out.append({
                "text": text,
                "svg": render_shaped_svg(font_obj, shaped),
                "glyphs": [g.name for g in shaped],
            })
        return out

    original_samples = render_set(font, order, font_bytes)
    shaped_samples = render_set(sub_shaped_font, sub_shaped_order, shaped_bytes)
    closure_samples = render_set(sub_closure_font, sub_closure_order,
                                 closure_bytes)

    # ---- 冲突分析（针对方案 B 的出包体积）----
    conflict = None
    if size_limit and closure_sizes["ttf"] > size_limit:
        probe_dir = os.path.join(build_dir, "probe")
        os.makedirs(probe_dir, exist_ok=True)

        def build_size(feature_set):
            if not feature_set:
                feature_set = set()
            tr = _closure_strategy_glyphs(font, corpus, feature_set)
            tag = hashlib.sha1(",".join(sorted(feature_set)).encode()).hexdigest()[:10]
            path = os.path.join(probe_dir, f"probe-{tag}.ttf")
            if not os.path.exists(path):
                build_subset(font_path, set(tr.glyphs), sorted(feature_set), path)
            return os.path.getsize(path)

        conflict = analyze_conflict(font_bytes, order, corpus, enabled,
                                    direction, size_limit, build_size)

    warnings = []
    if tracer.missing_codepoints:
        warnings.append(
            "语料中这些字符不在字体 cmap 里：" +
            " ".join(f"U+{cp:04X}" for cp in tracer.missing_codepoints))
    if degenerate:
        warnings.append("闭包结果等于整份字体，已拒绝原封导出，请缩小特性集合或语料。")
    if len(closure_glyphs) > 0.9 * orig_num_glyphs:
        warnings.append("闭包结果超过原字体 90%，接近整份导出。")

    def entries_for(sub_order, reasons, positioning):
        return [{
            "gid": gid,
            "name": name,
            "reason": reasons[name].to_json() if name in reasons else None,
            "positioning": positioning.get(name, []),
        } for gid, name in enumerate(sub_order)]

    result = {
        "build_id": build_id,
        "font_path": font_path,
        "features": sorted(enabled),
        "direction": direction,
        "size_limit": size_limit,
        "warnings": warnings,
        "samples": [{"text": t, "held_out": i >= len(corpus)}
                    for i, t in enumerate(all_samples)],
        "original": {
            "glyph_count": orig_num_glyphs,
            "size": os.path.getsize(font_path),
            "samples": original_samples,
        },
        "strategies": {
            "shaped": {
                "label": "实测字形裁剪",
                "glyph_count": len(shaped_glyphs),
                "size_ttf": shaped_sizes["ttf"],
                "size_woff2": shaped_sizes["woff2"],
                "download": {
                    "ttf": f"/api/download/{build_id}/shaped.ttf",
                    "woff2": f"/api/download/{build_id}/shaped.woff2",
                },
                "glyphs": entries_for(sub_shaped_order, shaped_reasons,
                                      shaped_pos),
                "verify": verify_shaped,
                "samples": shaped_samples,
            },
            "closure": {
                "label": "依赖闭包",
                "glyph_count": len(closure_glyphs),
                "size_ttf": closure_sizes["ttf"],
                "size_woff2": closure_sizes["woff2"],
                "download": {
                    "ttf": f"/api/download/{build_id}/closure.ttf",
                    "woff2": f"/api/download/{build_id}/closure.woff2",
                },
                "glyphs": entries_for(sub_closure_order, tracer.reasons,
                                      tracer.positioning),
                "verify": verify_closure,
                "samples": closure_samples,
            },
        },
        "conflict": conflict,
    }
    with open(os.path.join(build_dir, "manifest.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"font_path": font_path, "features": sorted(enabled),
                   "direction": direction}, fh)
    font.close()
    sub_shaped_font.close()
    sub_closure_font.close()
    return result
