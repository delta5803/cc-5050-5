"""端到端构建的不变量测试。"""

from fontTools.ttLib import TTFont

from .conftest import FONT_PATH


def test_closure_reproduces_all_samples(built):
    checks = built["strategies"]["closure"]["verify"]["sample_checks"]
    failed = [c["text"] for c in checks if not c["equal"]]
    assert not failed, f"闭包子集与原版整形不一致: {failed}"


def test_shaped_reproduces_training_but_not_heldout(built):
    checks = built["strategies"]["shaped"]["verify"]["sample_checks"]
    by_text = {c["text"]: c["equal"] for c in checks}
    for s in built["samples"]:
        if s["held_out"]:
            assert not by_text[s["text"]], \
                f"实测裁剪不应复现预留组合 {s['text']!r}"
        else:
            assert by_text[s["text"]], \
                f"实测裁剪应复现训练样本 {s['text']!r}"


def test_shaped_is_smaller(built):
    a = built["strategies"]["shaped"]
    b = built["strategies"]["closure"]
    assert a["glyph_count"] <= b["glyph_count"]
    assert a["size_ttf"] <= b["size_ttf"]


def test_closure_is_not_whole_font(built):
    b = built["strategies"]["closure"]
    assert b["glyph_count"] < built["original"]["glyph_count"] * 0.5
    assert not any("整份" in w for w in built["warnings"])


def test_mapping_and_outlines_verified(built):
    for key in ("shaped", "closure"):
        v = built["strategies"][key]["verify"]
        assert v["mapping_ok"]
        assert all(m["old_gid"] is not None for m in v["mapping"])
        assert v["outline_mismatches"] == []
        assert v["metric_mismatches"] == []


def test_subset_files_are_real_fonts(built):
    import os
    bid = built["build_id"]
    for strategy in ("shaped", "closure"):
        for ext in ("ttf", "woff2"):
            path = os.path.join(built["_out_root"], bid, f"{strategy}.{ext}")
            font = TTFont(path)
            assert font["maxp"].numGlyphs == \
                built["strategies"][strategy]["glyph_count"]
            assert "GSUB" in font
            font.close()


def test_subset_keeps_license_names(built):
    import os
    path = os.path.join(built["_out_root"], built["build_id"], "closure.ttf")
    font = TTFont(path)
    license_ids = {0, 13, 14}
    kept = {rec.nameID for rec in font["name"].names}
    assert license_ids & kept, "许可信息 name 记录应保留"
    font.close()


def test_woff2_smaller_than_ttf(built):
    for key in ("shaped", "closure"):
        s = built["strategies"][key]
        assert s["size_woff2"] < s["size_ttf"]


def test_every_glyph_has_reason(built):
    for key in ("shaped", "closure"):
        for g in built["strategies"][key]["glyphs"]:
            assert g["reason"] is not None, f"{key} 的 {g['name']} 缺少原因"
