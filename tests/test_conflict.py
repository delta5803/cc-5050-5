"""冲突分析：体积限制与排版行为无法兼得时报告首个冲突词。"""

from workbench import engine, samples

from .conftest import CORPUS, FEATURES, FONT_PATH, HELDOUT


def test_no_conflict_when_limit_generous(tmp_path):
    r = engine.build(FONT_PATH, FEATURES, "auto", CORPUS, HELDOUT,
                     size_limit=10 * 1024 * 1024,
                     out_root=str(tmp_path))
    assert r["conflict"] is None


def test_conflict_reports_first_word(tmp_path):
    # 先拿到无限制时的闭包体积，再设一个略小的限制
    r0 = engine.build(FONT_PATH, FEATURES, "auto", CORPUS, HELDOUT, None,
                      out_root=str(tmp_path))
    size = r0["strategies"]["closure"]["size_ttf"]
    r = engine.build(FONT_PATH, FEATURES, "auto", CORPUS, HELDOUT,
                     size_limit=size - 1, out_root=str(tmp_path))
    c = r["conflict"]
    assert c is not None
    assert c["feature"] in FEATURES
    assert c["word"] in CORPUS
    assert c["size_all"] == size
    assert c["limit"] == size - 1
    assert set(c["savings"]) == set(FEATURES)
    # 冲突词确实依赖该特性：去掉它后该词整形结果改变
    from workbench.hbshape import shape_text
    data = open(FONT_PATH, "rb").read()
    order = r0 and __import__("fontTools.ttLib", fromlist=["TTFont"]).TTFont(
        FONT_PATH).getGlyphOrder()
    feat_all = {t: True for t in FEATURES}
    feat_wo = dict(feat_all)
    feat_wo[c["feature"]] = False
    a = [g.key() for g in shape_text(data, order, c["word"], feat_all, "auto")]
    b = [g.key() for g in shape_text(data, order, c["word"], feat_wo, "auto")]
    assert a != b


def test_conflict_none_when_no_limit(tmp_path):
    r = engine.build(FONT_PATH, FEATURES, "auto", CORPUS, HELDOUT, None,
                     out_root=str(tmp_path))
    assert r["conflict"] is None
