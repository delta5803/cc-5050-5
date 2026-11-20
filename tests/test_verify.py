"""核对模块：能发现被篡改的差异。"""
from fontTools.ttLib import TTFont

from workbench.verify import (compare_metrics, compare_outlines,
                              compare_shaping, glyph_mapping)

from .conftest import FONT_PATH


def test_mapping_detects_missing_glyph(font, tmp_path):
    import os
    from workbench.subsetter import build_subset
    out = str(tmp_path / "sub.ttf")
    build_subset(FONT_PATH, {".notdef", "A", "V"}, ["kern"], out)
    sub = TTFont(out)
    mapping = glyph_mapping(font, sub)
    names = {m["name"] for m in mapping}
    assert names == {".notdef", "A", "V"}
    assert all(m["old_gid"] is not None for m in mapping)
    assert compare_outlines(font, sub) == []
    assert compare_metrics(font, sub) == []
    sub.close()


def test_compare_outlines_catches_tampering(font, tmp_path):
    from workbench.subsetter import build_subset
    out = str(tmp_path / "sub.ttf")
    build_subset(FONT_PATH, {".notdef", "A"}, ["kern"], out)
    sub = TTFont(out)
    # 篡改 A 的推进量
    adv, lsb = sub["hmtx"].metrics["A"]
    sub["hmtx"].metrics["A"] = (adv + 10, lsb)
    mismatches = compare_metrics(font, sub)
    assert any(m["name"] == "A" for m in mismatches)
    sub.close()


def test_compare_shaping_detects_difference(font, tmp_path):
    from workbench.subsetter import build_subset
    out = str(tmp_path / "sub.ttf")
    # 子集缺少 V，AV 的整形必然不同
    build_subset(FONT_PATH, {".notdef", "A"}, ["kern"], out)
    orig_bytes = open(FONT_PATH, "rb").read()
    sub_bytes = open(out, "rb").read()
    sub_order = TTFont(out).getGlyphOrder()
    report = compare_shaping(orig_bytes, font.getGlyphOrder(),
                             sub_bytes, sub_order, "AV", {"kern": True}, "ltr")
    assert not report["equal"]
    assert report["diffs"]
