"""体积限制与排版行为的冲突分析。

策略：闭包子集超过体积限制时，逐个评估"去掉某个特性"能省多少，
找出贡献最大的特性，再找到第一个依赖该特性的样本词，报告给用户。
"""
from __future__ import annotations

from .hbshape import shape_text


def _shaped_key(font_bytes, order, text, features, direction):
    return [g.key() for g in
            shape_text(font_bytes, order, text, features, direction)]


def analyze_conflict(font_bytes: bytes, glyph_order: list[str],
                     samples: list[str], features: set[str],
                     direction: str, size_limit: int,
                     build_size) -> dict:
    """build_size(feature_set) -> 该特性集合下闭包子集的字节数。"""
    size_all = build_size(features)
    if size_all <= size_limit:
        return None

    savings = {}
    sizes_without = {}
    for f in sorted(features):
        size_wo = build_size(features - {f})
        sizes_without[f] = size_wo
        savings[f] = size_all - size_wo

    # 省体积最多的特性是首要冲突来源
    culprit = max(sorted(features), key=lambda f: savings[f])

    feat_all = {t: True for t in features}
    feat_wo = dict(feat_all)
    feat_wo[culprit] = False
    word = None
    for text in samples:
        if _shaped_key(font_bytes, glyph_order, text, feat_all, direction) != \
           _shaped_key(font_bytes, glyph_order, text, feat_wo, direction):
            word = text
            break

    return {
        "feature": culprit,
        "word": word,
        "size_all": size_all,
        "size_without_feature": sizes_without[culprit],
        "limit": size_limit,
        "fits_without_feature": sizes_without[culprit] <= size_limit,
        "savings": {f: savings[f] for f in sorted(savings)},
    }
