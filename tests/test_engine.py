"""Recheck firmware-free calculations against the pinned whole-tuning digest record."""

from hashlib import sha256
from itertools import product
import random
import struct

import numpy as np
import pytest

from firmware_color_studio.engine import Engine, SLIDERS
from firmware_color_studio.profiles import LABELS

# Source: aa885bcdaee874d9b9bb18663dd62ed10263eda2, analysis/k3iii-color-engine-checks.json.
# The upstream test compared 10,087 cases with original firmware in the CPU emulator.
EXPECTED = {
    "bleach-bypass": "d3aaaa3a8da859e9b3065ac05a3ce600820f189744a4d19f5f822d24a49cee18",
    "bright": "ee7b1d8dc1e32ca8d640b55f3812b5da273c690f20e22fb565cd5879b2c08f7d",
    "cross-processing": "a1f79df45081ebbf42d5e9d0b98b7ea5ac9b66d943d3f442e42e6fd9078abbd0",
    "flat": "6f1a7ebe6f7e929b1fe893b3e530947d29fb2b17d92103601bf8c7a78c4b32da",
    "fuyuno": "78fc5ba38756667d7bd7ea3288847208424040c970a977aac6996f41403a7456",
    "gold": "1f090692317cfa065bbfbddba9b1fe7eea54d2fd4fe2dfda76399f5530d7a44b",
    "harubeni": "cc410863e140b2ba785c8b53fca1c5ff043e694f598b9214314b43d6c11ce580",
    "katen": "7c68e4e2fd0ec770031515bc1638a57ac257a1716c93af6a27216114cf3f90d3",
    "kyushu": "f566bbbd803b9e303bdb9f6d07bd631dfb93d2395ae7fd1469fbc7056ede7b8c",
    "landscape": "a28428c79fb70c5d1c6b3c8f95f7d9c49f86573fe53866c2b296113a948edc2a",
    "monochrome": "302a03fe68a6525681c14bfe3294b5e34efad931f71b68fadaa096b780ce1420",
    "muted": "585415cb9ba302cc90490f38019770f54eea88ee9a7b0813a58f729069e535d0",
    "natural": "d281cdb8d7cf120d6aacb2f4a94300f45c8783c49036811773af2e3229a2c445",
    "portrait": "59b53007f86d814dd12381c8e374d076039fcf606741c731a77fb8e429c2a748",
    "radiant": "854789b3cb460c7d6a5e85c954b31ecd6bea811c8312153bfeb944436c38b4f3",
    "reversal-film": "7914e68d3436b788136ab816eaa6bd3996d8965af4320ee611369be81e1fe43e",
    "satobi": "ae2154652ee502a1fb85bb2dc971989dbd1f303a781c49414d47563d854de52c",
    "vibrant": "c1dc0c54d1e71ced9c45edf35d1c526420557aa51730701c2cfb76aaa6ce2ec8",
}
TONE = ("key", "contrast", "highlight", "shadow")


@pytest.fixture(scope="module")
def engine():
    return Engine.load()


@pytest.mark.parametrize("mode", EXPECTED)
def test_whole_tuning_sample_matches_published_digest(engine, mode):
    entry = engine.modes[mode]
    cases = [{}] + [{key: value} for key in SLIDERS for value in range(-4, 5) if value]
    if entry["factory_settings"] is not None:
        cases.append({**engine.factory_settings(mode), "toning": engine.factory_toning(mode)})
    cases.extend({"toning": value} for value in range(1, 9))
    rng = random.Random(entry["number"])
    cases.extend({**{key: rng.randint(-4, 4) for key in SLIDERS}, "toning": rng.randint(0, 8)} for _ in range(40))

    digest = sha256()
    for space in ("srgb", "adobergb"):
        for case in cases:
            cc0 = engine.cc0(mode, case.get("saturation", 0), adobe_rgb=space == "adobergb")
            yc = engine.yc(mode, case.get("hue", 0))
            ycof = engine.chroma_offset(mode, case.get("toning", 0), space)
            digest.update(struct.pack("<9h9h2h", *cc0, *yc, *ycof))
            if mode in LABELS:
                gamma = engine.gamma(mode, **{key: case.get(key, 0) for key in TONE})
                digest.update(struct.pack("<256H", *gamma))
    assert digest.hexdigest() == EXPECTED[mode]


def test_all_6561_natural_tone_settings_match_published_digest(engine):
    digest = sha256()
    for values in product(range(-4, 5), repeat=4):
        curve = engine.gamma("natural", **dict(zip(TONE, values)))
        digest.update(np.asarray(curve, dtype="<u2").tobytes())
    assert digest.hexdigest() == "54b1538e20e1414e489aad8d3cc6cb3073c525663b3acae0af3ec4b1757c75f9"
