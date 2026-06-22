#!/usr/bin/env python3
"""Build and push the seed container image to ECR.

Run this AFTER deploying the runtime stack (Stack A) and BEFORE
deploying the app stack (Stack B).

Usage:
    python scripts/upload_seed_image.py \\
        --env-name arbitiumrs \\
        --aws-profile my-profile \\
        [--aws-region us-east-1] \\
        [--architecture x86_64|arm64] \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import boto3

_SEED_IMAGE_DIR = Path(__file__).resolve().parent / "backend" / "seed-image"
_SEED_TAG = "seed"


def _session(profile: Optional[str], region: str) -> boto3.Session:
    if profile:
        return boto3.Session(profile_name=profile, region_name=region)
    return boto3.Session(region_name=region)


def _ecr_repository_name(env_name: str) -> str:
    return f"{env_name}_backend"


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
    # ecr-public API is only available in us-east-1.
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
    architecture: str = "x86_64",
    dry_run: bool = False,
) -> str:
    """Build and push seed image. Returns the image URI."""
    session = _session(aws_profile, aws_region)
    account_id = session.client("sts").get_caller_identity()["Account"]
    registry = f"{account_id}.dkr.ecr.{aws_region}.amazonaws.com"
    repo_name = _ecr_repository_name(env_name)
    image_uri = f"{registry}/{repo_name}:{_SEED_TAG}"

    if dry_run:
        print(f"[dry-run] Would build and push: {image_uri}")
        return image_uri

    ecr = session.client("ecr")
    try:
        ecr.describe_repositories(repositoryNames=[repo_name])
    except ecr.exceptions.RepositoryNotFoundException:
        raise RuntimeError(
            f"ECR repository '{repo_name}' not found. "
            "Deploy the runtime stack (Stack A) first."
        )

    docker = _docker_executable()

    print("Logging in to public ECR (public.ecr.aws) for Lambda base image...")
    _ecr_public_login(session, docker)

    print(f"Logging in to private ECR registry: {registry}")
    _ecr_private_login(session, aws_region, docker)

    print(f"Building and pushing seed image: {image_uri}")
    _build_and_push(docker=docker, image_uri=image_uri, architecture=architecture)

    print(f"Seed image pushed successfully: {image_uri}")
    return image_uri


def main() -> None:
    parser = argparse.ArgumentParser(description="Push seed image to ECR (run between Stack A and Stack B).")
    parser.add_argument("--env-name", required=True, help="Environment name (e.g. arbitiumrs)")
    parser.add_argument("--aws-profile", default=None)
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--architecture", choices=["x86_64", "arm64"], default="x86_64")
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
    print("\nNext step: cdk deploy {env}-app")


if __name__ == "__main__":
    main()
