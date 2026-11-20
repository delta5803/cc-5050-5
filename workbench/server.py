"""HTTP 服务：静态页面 + JSON API。只用标准库。"""
from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fontTools.ttLib import TTFont

from . import engine, fontsource, samples
from .render import render_glyph_svg

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
OUT_ROOT = engine.OUT_ROOT


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "SubsetWorkbench/1.0"

    def log_message(self, fmt, *args):
        pass

    # ---------- helpers ----------
    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, code=200):
        self._send(code, _json_bytes(obj), "application/json; charset=utf-8")

    def _send_error_json(self, code, message):
        self._send_json({"error": message}, code)

    def _static_file(self, name, content_type):
        path = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(path):
            self._send_error_json(404, "not found")
            return
        with open(path, "rb") as fh:
            self._send(200, fh.read(), content_type)

    # ---------- GET ----------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._static_file("index.html", "text/html; charset=utf-8")
        if path == "/static/app.js":
            return self._static_file("app.js", "text/javascript; charset=utf-8")
        if path == "/static/style.css":
            return self._static_file("style.css", "text/css; charset=utf-8")
        if path == "/api/fonts":
            return self._send_json({"fonts": fontsource.list_fonts()})
        if path == "/api/defaults":
            return self._send_json({
                "corpus": samples.DEFAULT_CORPUS,
                "heldout": samples.DEFAULT_HELDOUT,
                "features": samples.DEFAULT_FEATURES,
            })
        m = re.fullmatch(r"/api/download/([0-9a-f]{12})/([\w.\-]+)", path)
        if m:
            return self._download(m.group(1), m.group(2))
        m = re.fullmatch(r"/api/glyph/([0-9a-f]{12})/(shaped|closure)/(.+)", path)
        if m:
            return self._glyph(m.group(1), m.group(2), m.group(3))
        self._send_error_json(404, "not found")

    def _download(self, build_id, filename):
        if not re.fullmatch(r"(shaped|closure)\.(ttf|woff2)", filename):
            return self._send_error_json(400, "bad filename")
        path = os.path.join(OUT_ROOT, build_id, filename)
        if not os.path.isfile(path):
            return self._send_error_json(404, "build not found")
        ctype = ("font/woff2" if filename.endswith(".woff2")
                 else "font/ttf")
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition",
                         f'attachment; filename="subset-{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _glyph(self, build_id, strategy, name):
        from urllib.parse import unquote
        name = unquote(name)
        build_dir = os.path.join(OUT_ROOT, build_id)
        manifest_path = os.path.join(build_dir, "manifest.json")
        sub_path = os.path.join(build_dir, f"{strategy}.ttf")
        if not os.path.isfile(manifest_path) or not os.path.isfile(sub_path):
            return self._send_error_json(404, "build not found")
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        try:
            sub_font = TTFont(sub_path)
            orig_font = TTFont(manifest["font_path"])
            out = {"name": name}
            out["subset_svg"] = (render_glyph_svg(sub_font, name)
                                 if name in sub_font.getGlyphOrder() else None)
            out["original_svg"] = (render_glyph_svg(orig_font, name)
                                   if name in orig_font.getGlyphOrder() else None)
            sub_font.close()
            orig_font.close()
            return self._send_json(out)
        except Exception as exc:
            return self._send_error_json(500, str(exc))

    # ---------- POST ----------
    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/build":
            return self._send_error_json(404, "not found")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._send_error_json(400, "invalid json")
        try:
            result = self._build(body)
        except ValueError as exc:
            return self._send_error_json(400, str(exc))
        except Exception as exc:
            return self._send_error_json(500, f"构建失败：{exc}")
        return self._send_json(result)

    def _build(self, body):
        font_info = fontsource.get_font(body.get("font_id", ""))
        if not font_info:
            raise ValueError("未知字体")
        features = body.get("features") or samples.DEFAULT_FEATURES
        known = set(font_info["gsub_features"]) | set(font_info["gpos_features"])
        features = [f for f in features if f in known]
        direction = body.get("direction", "auto")
        if direction not in ("auto", "ltr", "rtl"):
            raise ValueError("direction 必须是 auto/ltr/rtl")
        corpus = [s for s in (body.get("corpus") or []) if s.strip()]
        heldout = [s for s in (body.get("heldout") or []) if s.strip()]
        if not corpus:
            raise ValueError("训练语料不能为空")
        limit_kb = int(body.get("size_limit_kb") or 0)
        size_limit = limit_kb * 1024 if limit_kb > 0 else None

        result = engine.build(font_info["path"], features, direction,
                              corpus, heldout, size_limit)
        result["font"] = font_info
        return result


def run(host="127.0.0.1", port=8370):
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"字体子集排版工作台: http://{host}:{port}/")
    server.serve_forever()


if __name__ == "__main__":
    run()
