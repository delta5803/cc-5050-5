"""字体登记处：只收录确认的开放许可字体。"""
from __future__ import annotations

import os

from fontTools.ttLib import TTFont

FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts"),
]

# 开放许可白名单：按文件名识别，附许可说明
LICENSES = {
    "DejaVu": "Bitstream Vera License（开放许可，允许修改与再分发）",
}


def _name_record(font: TTFont, nid: int) -> str:
    for rec in font["name"].names:
        if rec.nameID == nid and rec.platformID == 3:
            try:
                return rec.toUnicode()
            except Exception:
                pass
    for rec in font["name"].names:
        if rec.nameID == nid:
            try:
                return rec.toUnicode()
            except Exception:
                pass
    return ""


def _license_for(path: str, font: TTFont) -> str | None:
    base = os.path.basename(path)
    for key, text in LICENSES.items():
        if key in base:
            return text
    # 字体自带许可说明非空时也认为可用（如 OFL 字体）
    lic = _name_record(font, 13) or _name_record(font, 14)
    if lic and any(k in lic.lower() for k in ("open font", "ofl", "bitstream vera",
                                              "sil open", "apache", "ubuntu font")):
        return lic.split("\n")[0][:120]
    return None


def list_fonts() -> list[dict]:
    out = []
    for d in FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith((".ttf", ".otf")):
                continue
            path = os.path.join(d, fn)
            try:
                font = TTFont(path, lazy=True)
                license_text = _license_for(path, font)
                if not license_text:
                    font.close()
                    continue
                gsub, gpos = [], []
                if "GSUB" in font:
                    gsub = sorted({r.FeatureTag for r in
                                   font["GSUB"].table.FeatureList.FeatureRecord})
                if "GPOS" in font:
                    gpos = sorted({r.FeatureTag for r in
                                   font["GPOS"].table.FeatureList.FeatureRecord})
                out.append({
                    "id": fn,
                    "path": path,
                    "family": _name_record(font, 1) or fn,
                    "style": _name_record(font, 2) or "",
                    "license": license_text,
                    "glyph_count": font["maxp"].numGlyphs,
                    "gsub_features": gsub,
                    "gpos_features": gpos,
                })
                font.close()
            except Exception:
                continue
    return out


def get_font(font_id: str) -> dict | None:
    for f in list_fonts():
        if f["id"] == font_id:
            return f
    return None
