"""HTTP API 测试：真实起服务、走完整请求。"""

import json
import threading
import urllib.request

import pytest

from workbench.server import ThreadingHTTPServer, Handler

from .conftest import CORPUS, FEATURES, HELDOUT


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def get(url):
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def test_fonts_endpoint(server):
    data = get(server + "/api/fonts")
    assert any(f["id"] == "DejaVuSans.ttf" for f in data["fonts"])
    for f in data["fonts"]:
        assert f["license"], "只应列出开放许可字体"


def test_defaults_endpoint(server):
    data = get(server + "/api/defaults")
    assert data["corpus"] and data["heldout"] and data["features"]


def test_build_and_download(server):
    result = post(server + "/api/build", {
        "font_id": "DejaVuSans.ttf",
        "features": FEATURES,
        "direction": "auto",
        "corpus": CORPUS,
        "heldout": HELDOUT,
        "size_limit_kb": 0,
    })
    assert result["build_id"]
    assert result["font"]["license"]
    url = server + result["strategies"]["closure"]["download"]["ttf"]
    with urllib.request.urlopen(url) as resp:
        body = resp.read()
    assert body[:4] == b"\x00\x01\x00\x00"  # 真实 TTF 魔数
    assert len(body) == result["strategies"]["closure"]["size_ttf"]
    woff2_url = server + result["strategies"]["closure"]["download"]["woff2"]
    with urllib.request.urlopen(woff2_url) as resp:
        assert resp.read()[:4] == b"wOF2"


def test_glyph_endpoint(server):
    result = post(server + "/api/build", {
        "font_id": "DejaVuSans.ttf",
        "features": FEATURES,
        "direction": "auto",
        "corpus": CORPUS,
        "heldout": HELDOUT,
        "size_limit_kb": 0,
    })
    bid = result["build_id"]
    data = get(f"{server}/api/glyph/{bid}/closure/uniFEFC")
    assert "<svg" in data["subset_svg"]
    assert "<svg" in data["original_svg"]


def test_build_rejects_unknown_font(server):
    with pytest.raises(Exception):
        post(server + "/api/build", {
            "font_id": "nope.ttf",
            "features": [],
            "direction": "auto",
            "corpus": ["x"],
            "heldout": [],
            "size_limit_kb": 0,
        })
