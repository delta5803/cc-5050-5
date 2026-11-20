import os

import pytest
from fontTools.ttLib import TTFont

from workbench import engine, samples

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
CORPUS = [s["text"] for s in samples.DEFAULT_CORPUS]
HELDOUT = [s["text"] for s in samples.DEFAULT_HELDOUT]
FEATURES = list(samples.DEFAULT_FEATURES)


@pytest.fixture(scope="session")
def font():
    f = TTFont(FONT_PATH)
    yield f
    f.close()


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("build")
    result = engine.build(FONT_PATH, FEATURES, "auto", CORPUS, HELDOUT, None,
                          out_root=str(out))
    result["_out_root"] = str(out)
    return result
