"""Write extension-install bootstrap output JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def write_extension_install_json(
    launcher_root: Path,
    env_name: str,
    payload: Mapping[str, Any],
) -> Path:
    path = launcher_root / f"{env_name}_extension_install.json"
    path.write_text(json.dumps(dict(payload), indent=2) + "\n", encoding="utf-8")
    return path
