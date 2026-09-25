#!/usr/bin/env python3
"""CDK app entry point.

Reads customer-config.json (same directory as this file) and instantiates two
platform stacks: <env>-stack-a (pre-seed) and <env>-stack-b (post-seed).

Stacks are environment-agnostic: account/region resolve at deploy time via
CloudFormation pseudo parameters (AWS::AccountId / AWS::Region). Synth is offline
and does not require aws_account / aws_region in customer-config.json.

Deploy order:
    cd bootstrap/output/<env_name>/cdk
    pip install -r requirements.txt

    # stack-a builds and pushes the seed image automatically (CodeBuild custom
    # resource); the deploy blocks until the build succeeds.
    cdk deploy <env>-stack-a --app "python app.py" [--parameters CreateGitHubOIDC=true]

    cdk deploy <env>-stack-b --app "python app.py" --output .
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import aws_cdk as cdk

_ROOT = Path(__file__).resolve().parent
_extra_paths = [_ROOT / "lib"]
for _p in (_ROOT, *_ROOT.parents):
    _scripts = _p / "bom-helper" / "scripts"
    _cdk = _p / "bom-helper" / "cdk"
    if _scripts.is_dir() or _cdk.is_dir():
        _extra_paths.extend((_scripts, _cdk))
        break
for _extra in _extra_paths:
    if _extra.is_dir() and str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from stack_names import stack_a_id, stack_b_id  # noqa: E402
from stacks.stack_a import StackA  # noqa: E402
from stacks.stack_b import StackB  # noqa: E402
from extension_loader import (  # noqa: E402
    load_extension_config,
    load_extension_manifest,
    resolve_extension_folder,
)
from platform_defaults import architecture as platform_architecture  # noqa: E402
from lib.package_registry import validate_package_registry  # noqa: E402
from extension_actions import (  # noqa: E402
    extra_action_roots,
    find_deploy_targets,
    hub_actions_specs,
    repo_workspace_root,
)

_CONFIG_PATH = _ROOT / "customer-config.json"
if not _CONFIG_PATH.is_file():
    _example = _ROOT / "customer-config.example.json"
    raise FileNotFoundError(
        f"customer-config.json not found at {_CONFIG_PATH}\n"
        f"Copy the example: cp {_example} {_CONFIG_PATH}"
    )

with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _cfg = json.load(_f)


def _require(key: str) -> str:
    v = _cfg.get(key, "").strip()
    if not v:
        raise ValueError(f"customer-config.json: required key '{key}' is missing or empty")
    return v


def _optional_id(key: str) -> str | None:
    v = str(_cfg.get(key, "") or "").strip()
    return v or None


env_name = _require("env_name")
github_repo = _require("github_repo")
github_owner_id = _optional_id("github_owner_id")
github_repo_id = _optional_id("github_repo_id")
enable_staging = bool(_cfg.get("enable_staging", True))
architecture = platform_architecture(config_dir=_ROOT)

extension_path = _cfg.get("extension_path", "").strip()
email_from = _require("email_from")
email_identity_type = _require("email_identity_type")
email_hosted_zone_id = str(_cfg.get("email_hosted_zone_id", "") or "").strip()

if email_identity_type not in ("email", "domain"):
    raise ValueError(
        f"customer-config.json: 'email_identity_type' must be email|domain, got {email_identity_type!r}"
    )

app = cdk.App()

try:
    package_registry = validate_package_registry(_cfg.get("package_registry"))
except ValueError as exc:
    raise ValueError(f"customer-config.json: {exc}") from exc

stack_a = StackA(
    app,
    stack_a_id(env_name),
    env_name=env_name,
    github_repo=github_repo,
    enable_staging=enable_staging,
    email_from=email_from,
    email_identity_type=email_identity_type,
    email_hosted_zone_id=email_hosted_zone_id,
    github_owner_id=github_owner_id,
    github_repo_id=github_repo_id,
    package_registry=package_registry,
)

extension_folder = None
extension_manifest = None
extension_config = None
if extension_path:
    extension_folder = resolve_extension_folder(extension_path)
    extension_manifest = load_extension_manifest(extension_folder)
    extension_config = load_extension_config(extension_folder)

_workspace = repo_workspace_root(start=_ROOT)
_targets = find_deploy_targets(cdk_dir=_ROOT, github_repo=github_repo)
_hub_actions = (
    hub_actions_specs(_targets, _workspace, extra_roots=extra_action_roots(_ROOT))
    if _targets is not None
    else []
)

stack_b = StackB(
    app,
    stack_b_id(env_name),
    env_name=env_name,
    github_repo=github_repo,
    enable_staging=enable_staging,
    architecture=architecture,
    tenant_role=stack_a.tt_role,
    stack_a_auth=stack_a.auth,
    stack_a_storage=stack_a.storage,
    stack_a_console=stack_a.console,
    stack_a_runtime=stack_a.runtime,
    stack_a_ai_storage=stack_a.ai_storage,
    from_email=stack_a.from_email,
    extension_folder=extension_folder,
    extension_manifest=extension_manifest,
    extension_config=extension_config,
    include_extension=extension_folder is not None and extension_manifest is not None,
    hub_actions_specs=_hub_actions,
)
stack_b.add_dependency(stack_a)

app.synth()
