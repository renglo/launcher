"""Load platform_defaults.json — centralized tunable defaults for CDK and install scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_VALID_ARCHITECTURES = frozenset({"x86_64", "arm64"})
_DEFAULTS_FILENAME = "platform_defaults.json"


def _defaults_path(config_dir: Path | None = None) -> Path:
    base = config_dir or Path(__file__).resolve().parent
    return base / _DEFAULTS_FILENAME


def load_platform_defaults(config_dir: Path | None = None) -> dict[str, Any]:
    path = _defaults_path(config_dir)
    if not path.is_file():
        raise FileNotFoundError(
            f"{_DEFAULTS_FILENAME} not found at {path}\n"
            "This file holds platform-wide defaults (architecture, seed image URI, etc.)."
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {key: value for key, value in raw.items() if not str(key).startswith("_")}


def architecture(defaults: dict[str, Any] | None = None, *, config_dir: Path | None = None) -> str:
    cfg = defaults if defaults is not None else load_platform_defaults(config_dir)
    arch = str(cfg.get("architecture", "x86_64")).strip() or "x86_64"
    if arch not in _VALID_ARCHITECTURES:
        raise ValueError(
            f"platform_defaults.json: 'architecture' must be one of {sorted(_VALID_ARCHITECTURES)}, got {arch!r}"
        )
    return arch


def lambda_architecture_cfn(arch: str) -> str:
    if arch not in _VALID_ARCHITECTURES:
        raise ValueError(f"Unsupported architecture: {arch!r}")
    return "x86_64" if arch == "x86_64" else "arm64"


def _backend_seed_cfg(defaults: dict[str, Any]) -> dict[str, Any]:
    seed_cfg = defaults.get("backend_seed_image")
    if not isinstance(seed_cfg, dict):
        return {}
    return seed_cfg


def backend_ecr_repository_name(
    env_name: str,
    defaults: dict[str, Any] | None = None,
    *,
    config_dir: Path | None = None,
) -> str:
    cfg = defaults if defaults is not None else load_platform_defaults(config_dir)
    suffix = str(_backend_seed_cfg(cfg).get("ecr_repository_suffix", "_backend"))
    return f"{env_name}{suffix}"


def backend_seed_image_uri(
    *,
    env_name: str,
    region: str,
    account: str,
    defaults: dict[str, Any] | None = None,
    config_dir: Path | None = None,
) -> str:
    cfg = defaults if defaults is not None else load_platform_defaults(config_dir)
    seed_cfg = _backend_seed_cfg(cfg)
    repo_name = backend_ecr_repository_name(env_name, cfg)
    image_tag = str(seed_cfg.get("image_tag", "seed"))
    template = str(
        seed_cfg.get(
            "uri_template",
            "{account}.dkr.ecr.{region}.amazonaws.com/{ecr_repository_name}:{image_tag}",
        )
    )
    return template.format(
        account=account,
        region=region,
        env_name=env_name,
        ecr_repository_name=repo_name,
        image_tag=image_tag,
    )
