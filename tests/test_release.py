"""Release metadata that the Windows build and the tag-triggered publish step rely on."""

import os
from pathlib import Path
import tomllib

from firmware_color_studio import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_metadata_release_notes_and_tag_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == __version__
    assert f'#define AppVersion "{__version__}"' in (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    # The publish step reads docs/releases/<tag>.md and names the installer after __version__.
    assert (ROOT / "docs" / "releases" / f"v{__version__}.md").is_file()
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        assert os.environ["GITHUB_REF_NAME"] == f"v{__version__}"
