#!/usr/bin/env python3
"""
Tighten EventBridge iam:PassRole in a tt_policy from role/* to {env_name}_tt_role.

Example:
  python dev/launcher/scripts/fix_eventbridge_passrole_policy.py arbitium_tt_policy
  python dev/launcher/scripts/fix_eventbridge_passrole_policy.py arbitium_tt_policy -p my-admin-profile
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import boto3


def _env_name_from_policy_name(policy_name: str) -> str:
    suffix = "_tt_policy"
    if policy_name.endswith(suffix):
        return policy_name[: -len(suffix)]
    return policy_name


def _is_eventbridge_passrole_statement(stmt: dict[str, Any]) -> bool:
    actions = stmt.get("Action")
    if isinstance(actions, str):
        actions = [actions]
    if "iam:PassRole" not in (actions or []):
        return False
    condition = stmt.get("Condition") or {}
    passed_to = (condition.get("StringEquals") or {}).get("iam:PassedToService")
    return passed_to == "events.amazonaws.com"


def _resource_is_broad_role_wildcard(resource: Any) -> bool:
    values = resource if isinstance(resource, list) else [resource]
    for value in values:
        text = str(value or "")
        if text.endswith(":role/*") or text.endswith(":role/*/*"):
            return True
    return False


def fix_eventbridge_passrole_policy(
    policy_name: str,
    *,
    env_name: str | None = None,
    profile: str | None = None,
    region: str = "us-east-1",
    apply_changes: bool = True,
) -> bool:
    """
    Replace EventBridge PassRole role/* with the environment tt role ARN.
    Returns True when a new policy version is created.
    """
    env = env_name or _env_name_from_policy_name(policy_name)
    tt_role_name = f"{env}_tt_role"

    session = boto3.Session(profile_name=profile, region_name=region)
    iam = session.client("iam")
    sts = session.client("sts")
    account_id = sts.get_caller_identity()["Account"]
    policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"
    scoped_role_arn = f"arn:aws:iam::{account_id}:role/{tt_role_name}"

    try:
        iam.get_policy(PolicyArn=policy_arn)
    except iam.exceptions.NoSuchEntityException:
        print(f"Policy '{policy_name}' not found.")
        return False

    policy_versions = iam.list_policy_versions(PolicyArn=policy_arn)
    current = next((v for v in policy_versions["Versions"] if v["IsDefaultVersion"]), None)
    if not current:
        print("Could not find default policy version.")
        return False

    current_doc = iam.get_policy_version(
        PolicyArn=policy_arn,
        VersionId=current["VersionId"],
    )["PolicyVersion"]["Document"]

    updated = False
    new_statements: list[dict[str, Any]] = []
    for stmt in current_doc.get("Statement", []):
        new_stmt = dict(stmt)
        if _is_eventbridge_passrole_statement(new_stmt) and _resource_is_broad_role_wildcard(
            new_stmt.get("Resource")
        ):
            new_stmt["Resource"] = scoped_role_arn
            new_stmt.setdefault("Sid", "EventBridgePassRole")
            updated = True
        new_statements.append(new_stmt)

    if not updated:
        print(
            f"No broad EventBridge PassRole statement found in '{policy_name}'. "
            f"Expected scoped role: {scoped_role_arn}"
        )
        return False

    new_doc = dict(current_doc)
    new_doc["Statement"] = new_statements

    if json.dumps(current_doc, sort_keys=True) == json.dumps(new_doc, sort_keys=True):
        print(f"Policy '{policy_name}' already scoped to {scoped_role_arn}.")
        return False

    print(f"Updating '{policy_name}' EventBridge PassRole -> {scoped_role_arn}")
    if not apply_changes:
        print(json.dumps(new_doc, indent=2))
        return True

    iam.create_policy_version(
        PolicyArn=policy_arn,
        PolicyDocument=json.dumps(new_doc),
        SetAsDefault=True,
    )
    print(f"Policy '{policy_name}' updated successfully.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scope EventBridge iam:PassRole in a tt_policy to {env_name}_tt_role."
    )
    parser.add_argument("policy_name", help="IAM policy name (e.g. arbitium_tt_policy)")
    parser.add_argument(
        "--env-name",
        help="Environment prefix when policy name is not {env}_tt_policy",
    )
    parser.add_argument(
        "--aws-profile",
        "-p",
        default=None,
        help="AWS profile (default: credential chain)",
    )
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the updated document without creating a policy version",
    )
    args = parser.parse_args()

    fix_eventbridge_passrole_policy(
        args.policy_name,
        env_name=args.env_name,
        profile=args.aws_profile,
        region=args.aws_region,
        apply_changes=not args.dry_run,
    )


if __name__ == "__main__":
    main()
