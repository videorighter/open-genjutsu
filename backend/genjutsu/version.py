"""The package manifest is the single source of the application version."""

import json
import os
from pathlib import Path

VERSION = json.loads(
    (Path(__file__).resolve().parents[2] / "package.json").read_text()
)["version"]
BUILD_REVISION = os.environ.get("GENJUTSU_BUILD_REVISION", "unknown")
