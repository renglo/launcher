#!/usr/bin/env python3
"""Build and push the seed container image to ECR.

Run this AFTER deploying <env>-stack-a and BEFORE deploying <env>-stack-b.

Usage (from monorepo root):
    python bootstrap/upload_seed_image.py \\
        --env-name <env> \\
        --aws-profile my-profile \\
        [--aws-region us-east-1] \\
        [--architecture x86_64|arm64] \\
        [--dry-run]

Usage (from launcher/scripts/):
    python scripts/upload_seed_image.py ...

Defaults (architecture, seed image tag/URI) come from launcher/cdk/platform_defaults.json.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import boto3

_ROOT = Path(__file__).resolve().parent
if (_ROOT / "platform_defaults.json").is_file():
    _CONFIG_DIR = _ROOT
    _SEED_IMAGE_DIR = _ROOT / "seed-image"
else:
    _CONFIG_DIR = _ROOT.parent / "cdk"
    _SEED_IMAGE_DIR = _ROOT / "backend" / "seed-image"

sys.path.insert(0, str(_CONFIG_DIR))

from platform_defaults import (  # noqa: E402
    architecture as default_architecture,
    backend_ecr_repository_name,
    backend_seed_image_uri,
    load_platform_defaults,
)


def _session(profile: Optional[str], region: str) -> boto3.Session:
    if profile:
        return boto3.Session(profile_name=profile, region_name=region)
    return boto3.Session(region_name=region)


def _docker_executable() -> str:
    if os.name == "nt":
        for candidate in ("docker.exe", "docker.cmd", "docker"):
            found = shutil.which(candidate)
            if found:
                return found
    found = shutil.which("docker")
    if found:
        return found
    raise RuntimeError("Docker not found in PATH. Install Docker and retry.")


def _docker_login(docker: str, registry: str, password: str) -> None:
    subprocess.run(
        [docker, "login", "--username", "AWS", "--password-stdin", registry],
        input=password,
        text=True,
        check=True,
    )


def _ecr_private_login(session: boto3.Session, aws_region: str, docker: str) -> str:
    ecr = session.client("ecr", region_name=aws_region)
    token_data = ecr.get_authorization_token()["authorizationData"][0]
    encoded = token_data["authorizationToken"]
    _, password = base64.b64decode(encoded).decode("utf-8").split(":", 1)
    endpoint = token_data["proxyEndpoint"].replace("https://", "")
    _docker_login(docker, endpoint, password)
    account_id = session.client("sts").get_caller_identity()["Account"]
    return f"{account_id}.dkr.ecr.{aws_region}.amazonaws.com"


def _ecr_public_login(session: boto3.Session, docker: str) -> None:
    """Authenticate Docker to public.ecr.aws (required to pull lambda/python base images)."""
    ecr_public = session.client("ecr-public", region_name="us-east-1")
    encoded = ecr_public.get_authorization_token()["authorizationData"]["authorizationToken"]
    _, password = base64.b64decode(encoded).decode("utf-8").split(":", 1)
    _docker_login(docker, "public.ecr.aws", password)


def _build_and_push(
    *,
    docker: str,
    image_uri: str,
    architecture: str,
) -> None:
    platform = "linux/amd64" if architecture == "x86_64" else "linux/arm64"
    dockerfile = _SEED_IMAGE_DIR / "Dockerfile"
    if not dockerfile.is_file():
        raise FileNotFoundError(f"Seed image Dockerfile not found: {dockerfile}")

    has_buildx = False
    try:
        subprocess.run([docker, "buildx", "version"], check=True, capture_output=True)
        has_buildx = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    if has_buildx:
        subprocess.run(
            [
                docker, "buildx", "build",
                "--platform", platform,
                "--provenance=false",
                "--sbom=false",
                "-t", image_uri,
                "-f", str(dockerfile),
                "--push",
                str(_SEED_IMAGE_DIR),
            ],
            check=True,
        )
    else:
        subprocess.run(
            [docker, "build", "--platform", platform, "-t", image_uri, "-f", str(dockerfile), str(_SEED_IMAGE_DIR)],
            check=True,
        )
        subprocess.run([docker, "push", image_uri], check=True)


def upload_seed_image(
    env_name: str,
    aws_profile: Optional[str],
    aws_region: str,
    architecture: str | None = None,
    dry_run: bool = False,
    *,
    defaults: dict | None = None,
) -> str:
    """Build and push seed image. Returns the image URI."""
    platform_defaults = defaults or load_platform_defaults(_CONFIG_DIR)
    arch = architecture or default_architecture(platform_defaults, config_dir=_CONFIG_DIR)
    session = _session(aws_profile, aws_region)
    account_id = session.client("sts").get_caller_identity()["Account"]
    repo_name = backend_ecr_repository_name(env_name, platform_defaults, config_dir=_CONFIG_DIR)
    image_uri = backend_seed_image_uri(
        env_name=env_name,
        region=aws_region,
        account=account_id,
        defaults=platform_defaults,
        config_dir=_CONFIG_DIR,
    )

    if dry_run:
        print(f"[dry-run] Would build and push: {image_uri}")
        return image_uri

    ecr = session.client("ecr")
    try:
        ecr.describe_repositories(repositoryNames=[repo_name])
    except ecr.exceptions.RepositoryNotFoundException:
        raise RuntimeError(
            f"ECR repository '{repo_name}' not found. "
            f"Deploy {env_name}-stack-a first."
        )

    docker = _docker_executable()

    print("Logging in to public ECR (public.ecr.aws) for Lambda base image...")
    _ecr_public_login(session, docker)

    registry = f"{account_id}.dkr.ecr.{aws_region}.amazonaws.com"
    print(f"Logging in to private ECR registry: {registry}")
    _ecr_private_login(session, aws_region, docker)

    print(f"Building and pushing seed image: {image_uri}")
    _build_and_push(docker=docker, image_uri=image_uri, architecture=arch)

    print(f"Seed image pushed successfully: {image_uri}")
    return image_uri


def main() -> None:
    default_arch = default_architecture(config_dir=_CONFIG_DIR)
    parser = argparse.ArgumentParser(
        description="Push seed image to ECR (run between <env>-stack-a and <env>-stack-b)."
    )
    parser.add_argument("--env-name", required=True, help="Environment name (e.g. arbitiumrs)")
    parser.add_argument("--aws-profile", default=None)
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument(
        "--architecture",
        choices=["x86_64", "arm64"],
        default=None,
        help=f"Override platform_defaults.json architecture (default: {default_arch})",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    uri = upload_seed_image(
        env_name=args.env_name,
        aws_profile=args.aws_profile,
        aws_region=args.aws_region,
        architecture=args.architecture,
        dry_run=args.dry_run,
    )
    print(f"\nSeed image URI: {uri}")
    print(f"\nNext step: deploy {args.env_name}-stack-b (CloudFormation or CDK)")


if __name__ == "__main__":
    main()
