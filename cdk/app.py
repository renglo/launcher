#!/usr/bin/env python3
"""CDK app entry point.

Reads customer-config.json (same directory as this file) and instantiates two
platform stacks: <env>-stack-a (pre-seed) and <env>-stack-b (post-seed).

Deploy order:
    cd bootstrap/output/<env_name>
    pip install -r requirements.txt

    cdk deploy <env>-stack-a --app "python app.py"

    python upload_seed_image.py \\
        --env-name <env_name> --aws-profile <profile>

    cdk deploy <env>-stack-b --app "python app.py" --output . [--parameters VpcId=... SubnetIds=...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import aws_cdk as cdk

_ROOT = Path(__file__).resolve().parent
_EXTENSIONS_DIR = _ROOT / "extensions"
if (_EXTENSIONS_DIR / "compute_stack.py").is_file():
    sys.path.insert(0, str(_EXTENSIONS_DIR))
else:
    sys.path.insert(0, str(_ROOT.parents[2] / "extensions-service" / "scripts"))

from stack_names import stack_a_id, stack_b_id  # noqa: E402
from stacks.stack_a import StackA  # noqa: E402
from stacks.stack_b import StackB  # noqa: E402
from extension_loader import (  # noqa: E402
    load_extension_config,
    load_extension_manifest,
    resolve_extension_folder,
)
from platform_defaults import architecture as platform_architecture  # noqa: E402

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


env_name = _require("env_name")
aws_account = _require("aws_account")
aws_region = _cfg.get("aws_region", "us-east-1").strip() or "us-east-1"
github_repo = _require("github_repo")
github_handlers_repo = _cfg.get("github_handlers_repo", github_repo).strip() or github_repo
enable_staging = bool(_cfg.get("enable_staging", True))
architecture = platform_architecture(config_dir=_ROOT)
compute_type = _cfg.get("compute_type", "fargate").strip() or "fargate"
ec2_instance_type = _cfg.get("ec2_instance_type", "t3.medium").strip() or "t3.medium"
ec2_min_instances = int(_cfg.get("ec2_min_instances", 0))
ec2_desired_instances = int(_cfg.get("ec2_desired_instances", 1))
ec2_max_instances = int(_cfg.get("ec2_max_instances", 2))
extension_path = _cfg.get("extension_path", "").strip()

if compute_type not in ("lambda_only", "fargate", "ec2"):
    raise ValueError(f"customer-config.json: 'compute_type' must be lambda_only|fargate|ec2, got {compute_type!r}")

app = cdk.App()
cdk_env = cdk.Environment(account=aws_account, region=aws_region)

stack_a = StackA(
    app,
    stack_a_id(env_name),
    env_name=env_name,
    aws_account=aws_account,
    aws_region=aws_region,
    github_repo=github_repo,
    enable_staging=enable_staging,
    env=cdk_env,
)

extension_folder = None
extension_manifest = None
extension_config = None
if extension_path:
    extension_folder = resolve_extension_folder(extension_path)
    extension_manifest = load_extension_manifest(extension_folder)
    extension_config = load_extension_config(extension_folder)

stack_b = StackB(
    app,
    stack_b_id(env_name),
    env_name=env_name,
    aws_account=aws_account,
    aws_region=aws_region,
    github_handlers_repo=github_handlers_repo,
    enable_staging=enable_staging,
    architecture=architecture,
    compute_type=compute_type,
    ec2_instance_type=ec2_instance_type,
    ec2_min_instances=ec2_min_instances,
    ec2_desired_instances=ec2_desired_instances,
    ec2_max_instances=ec2_max_instances,
    tenant_policy=stack_a.tt_policy,
    tenant_role=stack_a.tt_role,
    extension_folder=extension_folder,
    extension_manifest=extension_manifest,
    extension_config=extension_config,
    include_extension=extension_folder is not None and extension_manifest is not None,
    env=cdk_env,
)
stack_b.add_dependency(stack_a)

app.synth()
