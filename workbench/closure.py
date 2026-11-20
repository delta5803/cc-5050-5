"""依赖闭包追踪：沿启用的 GSUB 布局规则求字形闭包，并记录每个字形被留下的原因。

闭包语义镜像 fontTools.subset 的 closure_glyphs，但额外记录来源边，
使得每个保留下来的字形都能回答"它因哪个替换 / 复合轮廓引用而被留下"。
GPOS 不产生新字形，单独做定位关系标注。
"""
from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from fontTools.ttLib import TTFont


@dataclass
class Reason:
    kind: str            # root | cmap | gsub | composite
    feature: str | None  # 触发特性（gsub 时有效）
    lookup: int | None   # LookupList 下标
    detail: str
    sources: tuple[str, ...] = ()

    def to_json(self):
        return {
            "kind": self.kind,
            "feature": self.feature,
            "lookup": self.lookup,
            "detail": self.detail,
            "sources": list(self.sources),
        }


class ClosureTracer:
    def __init__(self, font: TTFont, features: set[str]):
        self.font = font
        self.features = features
        self.glyphs: set[str] = set()
        self.reasons: dict[str, Reason] = {}
        self.positioning: dict[str, list[str]] = {}
        self.missing_codepoints: list[int] = []
        self._lookup_memo: set[tuple[int, frozenset]] = set()
        self._feature_lookups = self._collect_gsub_lookups()

    # ---------- 种子 ----------
    def seed_codepoints(self, codepoints):
        cmap = self.font.getBestCmap()
        self._add(".notdef", Reason("root", None, None, "缺省字形 .notdef"))
        for cp in sorted(set(codepoints)):
            name = cmap.get(cp)
            if name is None:
                self.missing_codepoints.append(cp)
                continue
            ch = chr(cp)
            shown = ch if ch.isprintable() else ""
            self._add(name, Reason("cmap", None, None,
                                   f"语料字符 U+{cp:04X} {shown}".rstrip()))

    def seed_samples(self, samples):
        """语料字符种子 + 规范化闭包。

        HarfBuzz 整形前有规范化阶段：字体 cmap 里有预组字形时把
        基字+组合符合成预组字符（e + ◌́ → é），缺预组字形时反向分解。
        闭包必须镜像这一步，否则子集整形结果会与原版不同。
        """
        cps = set()
        for text in samples:
            cps.update(ord(ch) for ch in text)
        self.seed_codepoints(cps)

        cmap = self.font.getBestCmap()
        for text in samples:
            nfc = unicodedata.normalize("NFC", text)
            if nfc != text:
                for ch in nfc:
                    cp = ord(ch)
                    name = cmap.get(cp)
                    if name is None:
                        continue
                    decomp = unicodedata.normalize("NFD", ch)
                    src_names = tuple(cmap[ord(d)] for d in decomp
                                      if ord(d) in cmap)
                    seq = " ".join(f"U+{ord(d):04X}" for d in decomp)
                    self._add(name, Reason(
                        "norm", None, None,
                        f"规范化组合 {seq} → U+{cp:04X}", src_names))
            nfd = unicodedata.normalize("NFD", text)
            if nfd != text:
                for ch in text:
                    decomp = unicodedata.normalize("NFD", ch)
                    if len(decomp) <= 1:
                        continue
                    src = cmap.get(ord(ch))
                    for d in decomp:
                        name = cmap.get(ord(d))
                        if name is None:
                            continue
                        seq = " ".join(f"U+{ord(x):04X}" for x in decomp)
                        self._add(name, Reason(
                            "norm", None, None,
                            f"规范化分解 U+{ord(ch):04X} → {seq}",
                            (src,) if src else ()))

    # ---------- 主循环 ----------
    def run(self) -> set[str]:
        changed = True
        while changed:
            changed = False
            self._lookup_memo.clear()
            for feature, lookup_index in self._feature_lookups:
                lookup = self.font["GSUB"].table.LookupList.Lookup[lookup_index]
                changed |= self._closure_lookup(lookup, feature, lookup_index,
                                                frozenset(self.glyphs))
            changed |= self._closure_composites()
        return self.glyphs

    def _add(self, name: str, reason: Reason) -> bool:
        if name in self.glyphs:
            return False
        self.glyphs.add(name)
        self.reasons[name] = reason
        return True

    def _collect_gsub_lookups(self):
        out = []
        if "GSUB" not in self.font:
            return out
        gsub = self.font["GSUB"].table
        if not gsub.FeatureList:
            return out
        seen = set()
        for rec in gsub.FeatureList.FeatureRecord:
            if rec.FeatureTag not in self.features:
                continue
            for li in rec.Feature.LookupListIndex:
                if li not in seen:
                    seen.add(li)
                    out.append((rec.FeatureTag, li))
        return out

    # ---------- GSUB 闭包 ----------
    def _closure_lookup(self, lookup, feature, lookup_index, cur) -> bool:
        key = (lookup_index, cur)
        if key in self._lookup_memo:
            return False
        self._lookup_memo.add(key)
        changed = False
        for st in lookup.SubTable:
            if st is None:
                continue
            changed |= self._closure_subtable(st, feature, lookup_index, cur)
        return changed

    def _closure_subtable(self, st, feature, lookup_index, cur) -> bool:
        cls = st.__class__.__name__
        if cls == "SingleSubst":
            return self._cl_single(st, feature, lookup_index, cur)
        if cls == "MultipleSubst":
            return self._cl_multiple(st, feature, lookup_index, cur)
        if cls == "AlternateSubst":
            return self._cl_alternate(st, feature, lookup_index, cur)
        if cls == "LigatureSubst":
            return self._cl_ligature(st, feature, lookup_index, cur)
        if cls == "ReverseChainSingleSubst":
            return self._cl_reverse_chain(st, feature, lookup_index, cur)
        if cls in ("ContextSubst", "ChainContextSubst"):
            return self._cl_context(st, feature, lookup_index, cur)
        if cls == "ExtensionSubst":
            if st.Format == 1:
                return self._closure_subtable(st.ExtSubTable, feature,
                                              lookup_index, cur)
            raise ValueError(f"unknown ExtensionSubst format {st.Format}")
        return False

    def _cl_single(self, st, feature, li, cur):
        changed = False
        for src, dst in st.mapping.items():
            if src in cur:
                changed |= self._add(dst, Reason(
                    "gsub", feature, li,
                    f"单替换 {src} → {dst}", (src,)))
        return changed

    def _cl_multiple(self, st, feature, li, cur):
        changed = False
        for src, dsts in st.mapping.items():
            if src in cur:
                for dst in dsts:
                    changed |= self._add(dst, Reason(
                        "gsub", feature, li,
                        f"多替换 {src} → {' '.join(dsts)}", (src,)))
        return changed

    def _cl_alternate(self, st, feature, li, cur):
        changed = False
        for src, alts in st.alternates.items():
            if src in cur:
                for dst in alts:
                    changed |= self._add(dst, Reason(
                        "gsub", feature, li,
                        f"候选替换 {src} → {dst}（备选集合之一）", (src,)))
        return changed

    def _cl_ligature(self, st, feature, li, cur):
        changed = False
        for first, ligsets in st.ligatures.items():
            if first not in cur:
                continue
            for lig in ligsets:
                comps = list(lig.Component)
                if all(c in self.glyphs for c in comps):
                    seq = " + ".join([first] + comps)
                    changed |= self._add(lig.LigGlyph, Reason(
                        "gsub", feature, li,
                        f"连字 {seq} → {lig.LigGlyph}",
                        tuple([first] + comps)))
        return changed

    def _cl_reverse_chain(self, st, feature, li, cur):
        if st.Format != 1:
            raise ValueError(f"unknown ReverseChain format {st.Format}")
        indices = st.Coverage.intersect(cur)
        if not indices:
            return False
        coverages = list(st.LookAheadCoverage) + list(st.BacktrackCoverage)
        if not all(c.intersect(self.glyphs) for c in coverages):
            return False
        changed = False
        cov_glyphs = st.Coverage.glyphs
        for i in indices:
            src, dst = cov_glyphs[i], st.Substitute[i]
            changed |= self._add(dst, Reason(
                "gsub", feature, li,
                f"逆向链式替换 {src} → {dst}", (src,)))
        return changed

    # ----- 上下文 / 链式上下文 -----
    def _cl_context(self, st, feature, li, cur):
        is_chain = st.__class__.__name__ == "ChainContextSubst"
        if st.Format == 1:
            return self._cl_context_f1(st, is_chain, feature, li, cur)
        if st.Format == 2:
            return self._cl_context_f2(st, is_chain, feature, li, cur)
        if st.Format == 3:
            return self._cl_context_f3(st, is_chain, feature, li, cur)
        raise ValueError(f"unknown context format {st.Format}")

    def _apply_records(self, records, pos_glyphs_list, feature, li):
        """对一条命中规则的嵌套替换记录求闭包。pos_glyphs_list[i] 是序列位置 i
        上可能的字形集合；同一位置出现多次时退化为全集合（与 fontTools 一致）。"""
        changed = False
        seen_pos = set()
        for rec in records:
            seqi = rec.SequenceIndex
            if seqi in seen_pos or seqi >= len(pos_glyphs_list):
                pos = frozenset(self.glyphs)
            else:
                pos = frozenset(pos_glyphs_list[seqi])
            seen_pos.add(seqi)
            if not pos:
                continue
            nested = self.font["GSUB"].table.LookupList.Lookup[rec.LookupListIndex]
            changed |= self._closure_lookup(nested, feature, li, pos)
        return changed

    def _cl_context_f1(self, st, is_chain, feature, li, cur):
        cov = st.Coverage.glyphs
        matched = [i for i, g in enumerate(cov) if g in cur]
        if not matched:
            return False
        rulesets = st.ChainSubRuleSet if is_chain else st.SubRuleSet
        rule_attr = "ChainSubRule" if is_chain else "SubRule"
        changed = False
        for i in matched:
            if i >= len(rulesets) or not rulesets[i]:
                continue
            for rule in getattr(rulesets[i], rule_attr):
                if rule is None:
                    continue
                backtrack = list(rule.Backtrack) if is_chain else []
                inputs = list(rule.Input)
                lookahead = list(rule.LookAhead) if is_chain else []
                if not all(g in self.glyphs for g in backtrack + inputs + lookahead):
                    continue
                pos_glyphs = [{cov[i]}] + [{g} for g in inputs]
                changed |= self._apply_records(
                    rule.SubstLookupRecord, pos_glyphs, feature, li)
        return changed

    def _cl_context_f2(self, st, is_chain, feature, li, cur):
        cov = st.Coverage.glyphs
        matched = [i for i, g in enumerate(cov) if g in cur]
        if not matched:
            return False
        if is_chain:
            classdef = st.InputClassDef
            back_def, look_def = st.BacktrackClassDef, st.LookAheadClassDef
            classsets = st.ChainSubClassSet
            rule_attr = "ChainSubClassRule"
        else:
            classdef = st.ClassDef
            back_def = look_def = None
            classsets = st.SubClassSet
            rule_attr = "SubClassRule"

        def cls_of(cd, g):
            return cd.classDefs.get(g, 0) if cd else 0

        def cls_glyphs(cd, k):
            if cd is None:
                return set(self.glyphs) if k == 0 else set()
            return {g for g in self.glyphs if cd.classDefs.get(g, 0) == k}

        changed = False
        for i in matched:
            first_cls = cls_of(classdef, cov[i])
            if first_cls >= len(classsets) or not classsets[first_cls]:
                continue
            for rule in getattr(classsets[first_cls], rule_attr):
                if rule is None:
                    continue
                backtrack = list(rule.Backtrack) if is_chain else []
                inputs = list(rule.Input)
                lookahead = list(rule.LookAhead) if is_chain else []
                ok = all(cls_glyphs(back_def, k) for k in backtrack)
                ok = ok and all(cls_glyphs(classdef, k) for k in inputs)
                ok = ok and all(cls_glyphs(look_def, k) for k in lookahead)
                if not ok:
                    continue
                pos_glyphs = [{cov[i]}] + [cls_glyphs(classdef, k) for k in inputs]
                changed |= self._apply_records(
                    rule.SubstLookupRecord, pos_glyphs, feature, li)
        return changed

    def _cl_context_f3(self, st, is_chain, feature, li, cur):
        if is_chain:
            back_covs = list(st.BacktrackCoverage)
            input_covs = list(st.InputCoverage)
            look_covs = list(st.LookAheadCoverage)
        else:
            back_covs, look_covs = [], []
            input_covs = list(st.Coverage)
        if not input_covs or not input_covs[0].intersect(cur):
            return False
        all_covs = back_covs + input_covs[1:] + look_covs
        if not all(c.intersect(self.glyphs) for c in all_covs):
            return False
        pos_glyphs = [set(input_covs[0].intersect_glyphs(cur))]
        pos_glyphs += [set(c.intersect_glyphs(self.glyphs))
                       for c in input_covs[1:]]
        return self._apply_records(st.SubstLookupRecord, pos_glyphs, feature, li)

    # ----- 复合轮廓 -----
    def _closure_composites(self) -> bool:
        if "glyf" not in self.font:
            return False
        glyf = self.font["glyf"]
        changed = False
        for name in list(self.glyphs):
            g = glyf[name]
            if g.isComposite():
                for comp in g.components:
                    changed |= self._add(comp.glyphName, Reason(
                        "composite", None, None,
                        f"复合轮廓 {name} 引用的组件", (name,)))
        return changed

    # ---------- GPOS 定位关系标注（不产生新字形） ----------
    def annotate_positioning(self):
        if "GPOS" not in self.font:
            return
        gpos = self.font["GPOS"].table
        if not gpos.FeatureList:
            return
        seen = set()
        for rec in gpos.FeatureList.FeatureRecord:
            if rec.FeatureTag not in self.features:
                continue
            for li in rec.Feature.LookupListIndex:
                if li in seen:
                    continue
                seen.add(li)
                lookup = gpos.LookupList.Lookup[li]
                for st in lookup.SubTable:
                    self._annotate_pos_subtable(st, rec.FeatureTag)

    def _note(self, name, text):
        if name in self.glyphs:
            slot = self.positioning.setdefault(name, [])
            if text not in slot:
                slot.append(text)

    def _annotate_pos_subtable(self, st, feature):
        cls = st.__class__.__name__
        if cls == "PairPos":
            self._annotate_pair(st, feature)
        elif cls == "MarkBasePos":
            for g in st.MarkCoverage.glyphs:
                self._note(g, f"{feature}：作为附加符号附着到基字")
            for g in st.BaseCoverage.glyphs:
                self._note(g, f"{feature}：作为基字承接附加符号")
        elif cls == "MarkMarkPos":
            for g in st.Mark1Coverage.glyphs:
                self._note(g, f"{feature}：叠加到下层附加符号")
            for g in st.Mark2Coverage.glyphs:
                self._note(g, f"{feature}：承接上层附加符号")
        elif cls == "MarkLigPos":
            for g in st.MarkCoverage.glyphs:
                self._note(g, f"{feature}：附着到连字部件")
            for g in st.LigatureCoverage.glyphs:
                self._note(g, f"{feature}：作为连字承接附加符号")
        elif cls == "CursivePos":
            for g in st.Coverage.glyphs:
                self._note(g, f"{feature}：连写锚点")
        elif cls == "ExtensionPos" and st.Format == 1:
            self._annotate_pos_subtable(st.ExtSubTable, feature)

    def _annotate_pair(self, st, feature):
        if st.Format == 1:
            for left, pairset in zip(st.Coverage.glyphs, st.PairSet):
                for pair in pairset.PairValueRecord:
                    right = pair.SecondGlyph
                    self._note(left, f"{feature}：与 {right} 成对调整")
                    self._note(right, f"{feature}：与 {left} 成对调整")
        elif st.Format == 2:
            lefts = set(st.ClassDef1.classDefs) | set(st.Coverage.glyphs)
            rights = set(st.ClassDef2.classDefs)
            for g in lefts | rights:
                self._note(g, f"{feature}：参与类对字距调整")


def collect_positioning(font: TTFont, features: set[str], glyphs: set[str]):
    """独立调用：对给定字形集合生成定位关系标注。"""
    tracer = ClosureTracer(font, features)
    tracer.glyphs = set(glyphs)
    tracer.annotate_positioning()
    return tracer.positioning


def reverse_input_closure(font: TTFont, features: set[str],
                          glyphs: set[str],
                          reasons: dict | None = None) -> set[str]:
    """逆向输入闭包：若某条替换规则的输出已在集合中，把它的输入也补进来。

    整形是流水线的：连字等规则的输入往往是中间阶段的字形（如阿拉伯文
    lam-alef 连字的输入是 lam/alef 的词形变化形），它们不出现在最终输出里，
    但子集缺少它们就无法复现同一条整形链路。本闭包把这些中间字形补齐。
    """
    result = set(glyphs)
    if "GSUB" not in font:
        return result
    gsub = font["GSUB"].table
    if not gsub.FeatureList:
        return result
    lookups = []
    seen = set()
    for rec in gsub.FeatureList.FeatureRecord:
        if rec.FeatureTag not in features:
            continue
        for li in rec.Feature.LookupListIndex:
            if li not in seen:
                seen.add(li)
                lookups.append((rec.FeatureTag, li, gsub.LookupList.Lookup[li]))

    def note(name, feature, li, detail, sources):
        if reasons is not None and name not in reasons:
            reasons[name] = Reason("gsub", feature, li, detail, sources)

    def reverse_lookup(lookup, feature, li) -> bool:
        changed = False
        for st in lookup.SubTable:
            if st is None:
                continue
            changed |= reverse_subtable(st, feature, li)
        return changed

    def reverse_subtable(st, feature, li) -> bool:
        cls = st.__class__.__name__
        changed = False
        if cls == "SingleSubst":
            for src, dst in st.mapping.items():
                if dst in result and src not in result:
                    result.add(src)
                    note(src, feature, li,
                         f"中间阶段输入：{src} 经单替换得到 {dst}", (dst,))
                    changed = True
        elif cls == "MultipleSubst":
            for src, dsts in st.mapping.items():
                if dsts and all(d in result for d in dsts) and src not in result:
                    result.add(src)
                    note(src, feature, li,
                         f"中间阶段输入：{src} 经多替换得到 {' '.join(dsts)}",
                         tuple(dsts))
                    changed = True
        elif cls == "AlternateSubst":
            for src, alts in st.alternates.items():
                if any(a in result for a in alts) and src not in result:
                    result.add(src)
                    note(src, feature, li,
                         f"中间阶段输入：{src} 的候选替换在集合中", ())
                    changed = True
        elif cls == "LigatureSubst":
            for first, ligsets in st.ligatures.items():
                for lig in ligsets:
                    if lig.LigGlyph in result:
                        for g in [first] + list(lig.Component):
                            if g not in result:
                                result.add(g)
                                note(g, feature, li,
                                     f"中间阶段输入：参与连字 {lig.LigGlyph}",
                                     (lig.LigGlyph,))
                                changed = True
        elif cls == "ReverseChainSingleSubst":
            if st.Format == 1:
                cov = st.Coverage.glyphs
                for i, dst in enumerate(st.Substitute):
                    if dst in result and cov[i] not in result:
                        result.add(cov[i])
                        note(cov[i], feature, li,
                             f"中间阶段输入：{cov[i]} 经逆向链式替换得到 {dst}",
                             (dst,))
                        changed = True
        elif cls in ("ContextSubst", "ChainContextSubst"):
            for records in _context_records(st):
                for rec in records:
                    nested = gsub.LookupList.Lookup[rec.LookupListIndex]
                    changed |= reverse_lookup(nested, feature,
                                              rec.LookupListIndex)
        elif cls == "ExtensionSubst":
            if st.Format == 1:
                changed |= reverse_subtable(st.ExtSubTable, feature, li)
        return changed

    changed = True
    while changed:
        changed = False
        for feature, li, lookup in lookups:
            changed |= reverse_lookup(lookup, feature, li)
    return result


def _context_records(st):
    """取上下文子表中全部规则的嵌套替换记录列表。"""
    out = []
    cls = st.__class__.__name__
    is_chain = cls == "ChainContextSubst"
    if st.Format == 1:
        rulesets = st.ChainSubRuleSet if is_chain else st.SubRuleSet
        attr = "ChainSubRule" if is_chain else "SubRule"
        for rs in rulesets:
            if not rs:
                continue
            for rule in getattr(rs, attr):
                if rule is not None:
                    out.append(list(rule.SubstLookupRecord))
    elif st.Format == 2:
        classsets = st.ChainSubClassSet if is_chain else st.SubClassSet
        attr = "ChainSubClassRule" if is_chain else "SubClassRule"
        for cs in classsets:
            if not cs:
                continue
            for rule in getattr(cs, attr):
                if rule is not None:
                    out.append(list(rule.SubstLookupRecord))
    elif st.Format == 3:
        out.append(list(st.SubstLookupRecord))
    return out
