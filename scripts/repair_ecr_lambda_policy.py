#!/usr/bin/env python3
"""Re-apply ECR repository policy so Lambda can pull backend container images."""

from __future__ import annotations

import argparse

import boto3

from provision_backend_infra import _ensure_ecr_lambda_pull_policy, _ecr_repository_name


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set ECR repository policy for Lambda image pull (fixes CreateFunction AccessDeniedException)."
    )
    parser.add_argument("environment_name", help="Environment name (e.g. arbitiumrs)")
    parser.add_argument("--aws-profile", required=True)
    parser.add_argument("--aws-region", default="us-east-1")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.aws_profile, region_name=args.aws_region)
    repo = _ecr_repository_name(args.environment_name)
    _ensure_ecr_lambda_pull_policy(session, repo, apply_changes=True)
    print(f"OK: ECR repository policy applied on {repo}")


if __name__ == "__main__":
    main()
