#!/usr/bin/env python3
"""CDK app entry point.

Reads customer-config.json (same directory as this file) and instantiates all
platform stacks.

Deploy order:
    cd launcher/cdk
    pip install -r requirements.txt

    # Stack A — ECR, IAM, CodeDeploy, OIDC
    cdk deploy {env_name}-runtime

    # Seed image — build + push to ECR before Lambda can be created
    python ../scripts/upload_seed_image.py --env-name {env_name} --aws-profile {profile}

    # Stack B — Lambda + API Gateway
    cdk deploy {env_name}-app

    # Remaining stacks (can be deployed in parallel after Stack A)
    cdk deploy {env_name}-compute
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import aws_cdk as cdk

# Add extensions-service/scripts to path so ComputeStack is importable.
_INFRA_INSTALLER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_INFRA_INSTALLER_ROOT / "extensions-service" / "scripts"))
from compute_stack import ComputeStack  # noqa: E402

from stacks.app import AppStack
from stacks.auth import AuthStack
from stacks.runtime import RuntimeStack
from stacks.storage import StorageStack

# ---------------------------------------------------------------------------
# Load customer config
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent / "customer-config.json"
if not _CONFIG_PATH.is_file():
    _example = Path(__file__).parent / "customer-config.example.json"
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
architecture = _cfg.get("architecture", "x86_64").strip() or "x86_64"
compute_type = _cfg.get("compute_type", "fargate").strip() or "fargate"
ec2_instance_type = _cfg.get("ec2_instance_type", "t3.medium").strip() or "t3.medium"

if architecture not in ("x86_64", "arm64"):
    raise ValueError(f"customer-config.json: 'architecture' must be 'x86_64' or 'arm64', got {architecture!r}")
if compute_type not in ("lambda_only", "fargate", "ec2"):
    raise ValueError(f"customer-config.json: 'compute_type' must be lambda_only|fargate|ec2, got {compute_type!r}")

# ---------------------------------------------------------------------------
# CDK app
# ---------------------------------------------------------------------------

app = cdk.App()

cdk_env = cdk.Environment(account=aws_account, region=aws_region)

auth_stack = AuthStack(
    app,
    f"{env_name}-auth",
    env_name=env_name,
    env=cdk_env,
)

storage_stack = StorageStack(
    app,
    f"{env_name}-storage",
    env_name=env_name,
    aws_account=aws_account,
    aws_region=aws_region,
    env=cdk_env,
)

# Stack A — ECR + IAM + CodeDeploy + OIDC (no Lambda, no API Gateway)
runtime_stack = RuntimeStack(
    app,
    f"{env_name}-runtime",
    env_name=env_name,
    aws_account=aws_account,
    aws_region=aws_region,
    github_repo=github_repo,
    cognito_user_pool_id=auth_stack.user_pool_id,
    s3_bucket_name=storage_stack.bucket_name,
    enable_staging=enable_staging,
    env=cdk_env,
)
runtime_stack.add_dependency(auth_stack)
runtime_stack.add_dependency(storage_stack)

# Stack B — Lambda (seed image) + API Gateway
# Deploy AFTER running scripts/upload_seed_image.py
app_stack = AppStack(
    app,
    f"{env_name}-app",
    env_name=env_name,
    aws_account=aws_account,
    aws_region=aws_region,
    enable_staging=enable_staging,
    architecture=architecture,
    env=cdk_env,
)
app_stack.add_dependency(runtime_stack)

compute_stack = ComputeStack(
    app,
    f"{env_name}-compute",
    env_name=env_name,
    aws_account=aws_account,
    aws_region=aws_region,
    compute_type=compute_type,
    ec2_instance_type=ec2_instance_type,
    github_handlers_repo=github_handlers_repo,
    enable_staging=enable_staging,
    env=cdk_env,
)
compute_stack.add_dependency(runtime_stack)

app.synth()
