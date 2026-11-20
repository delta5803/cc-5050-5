"""闭包追踪器的单元测试。"""
from fontTools.ttLib import TTFont

from workbench.closure import ClosureTracer, reverse_input_closure
from workbench.hbshape import feature_switches, shape_text

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FEATS = {"ccmp", "locl", "rlig", "liga", "init", "medi", "fina",
         "kern", "mark", "mkmk"}


def make_tracer(font, corpus, features=FEATS):
    tracer = ClosureTracer(font, features)
    tracer.seed_samples(corpus)
    tracer.run()
    return tracer


def test_liga_closure_with_reason(font):
    tr = make_tracer(font, ["office"])
    assert "uniFB03" in tr.glyphs  # ffi 连字
    reason = tr.reasons["uniFB03"]
    assert reason.kind == "gsub"
    assert reason.feature == "liga"
    assert "f" in reason.sources


def test_normalization_closure(font):
    # e + U+0301 的预组字形 é 必须经规范化闭包进入集合
    tr = make_tracer(font, ["café"])
    assert "eacute" in tr.glyphs
    assert tr.reasons["eacute"].kind == "norm"
    # 组合符本身也要在
    assert "acutecomb" in tr.glyphs


def test_composite_closure(font):
    # 直接用码点播种（不走规范化闭包），隔离测试复合轮廓闭包
    tr = ClosureTracer(font, FEATS)
    tr.seed_codepoints([0x00E9])  # é 预组字符
    tr.run()
    assert "eacute" in tr.glyphs
    # eacute 是复合轮廓，其组件应被复合闭包收入并记录原因
    glyf = font["glyf"]
    comps = [c.glyphName for c in glyf["eacute"].components]
    assert comps, "eacute 应为复合字形"
    for comp in comps:
        assert comp in tr.glyphs
        assert tr.reasons[comp].kind == "composite"


def test_arabic_closure_covers_unshaped_forms(font):
    corpus = ["سلام"]
    tr = make_tracer(font, corpus)
    # 实测整形只产出部分词形
    data = open(FONT_PATH, "rb").read()
    order = font.getGlyphOrder()
    switches = feature_switches([], FEATS)
    shaped = {g.name for g in shape_text(data, order, "سلام", switches, "auto")}
    # meem 的词首形 uniFEE3 不在实测输出里，但应被 init 闭包收入
    assert "uniFEE3" not in shaped
    assert "uniFEE3" in tr.glyphs
    assert tr.reasons["uniFEE3"].feature == "init"
    # lam 的中介形也应被 medi 闭包收入
    assert "uniFEE0" in tr.glyphs


def test_closure_is_not_whole_font(font):
    tr = make_tracer(font, ["office", "fluff", "سلام", "שלום"])
    total = font["maxp"].numGlyphs
    assert len(tr.glyphs) < total * 0.5


def test_reverse_input_closure_pulls_ligature_inputs(font):
    # 只给连字输出，逆向闭包应补回它的输入字形
    result = reverse_input_closure(font, {"rlig"}, {"uniFEFC", "uni0644",
                                                    "uni0627"})
    assert "uniFEE0" in result  # lam 中介形（uniFEFC 的输入之一）
    assert "uniFE8E" in result  # alef 词尾形


def test_positioning_annotation(font):
    tr = make_tracer(font, ["AVATAR"])
    tr.annotate_positioning()
    assert any("kern" in note for note in tr.positioning.get("A", []))


def test_missing_codepoint_reported(font):
    tr = ClosureTracer(font, FEATS)
    tr.seed_samples(["兔🐰"])  # 兔子和 emoji 不在 DejaVu Sans 里
    assert 0x1F430 in tr.missing_codepoints
