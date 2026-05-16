"""Reverse deploy_environment.py: delete all provisioned resources for an environment.

Reads launcher/state/<env>/created_resources.json (written by deploy_environment.py)
and deletes resources in reverse provisioning order.

Usage:
    python teardown_environment.py <environment_name> \\
        --aws-profile acd-arbitium-tt-dev \\
        --aws-region us-east-1 \\
        [--yes] [--skip-tables] [--skip-cognito] [--keep-logs]

The OIDC provider token.actions.githubusercontent.com is not removed (often shared across tenants).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Callable

import boto3

_LAUNCHER_ROOT = Path(__file__).resolve().parent.parent


def _session(profile: str, region: str) -> boto3.Session:
    return boto3.Session(profile_name=profile, region_name=region)


def _load_manifest(env_name: str, aws_region: str) -> tuple[dict[str, Any], Path]:
    state_dir = _LAUNCHER_ROOT / "state" / env_name
    json_path = state_dir / "created_resources.json"
    if not json_path.is_file():
        raise FileNotFoundError(
            f"No state found at {json_path}.\n"
            f"Run 'deploy_environment.py {env_name} ...' first, or check that the state dir exists."
        )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    region = data.get("aws_region") or aws_region
    return data, state_dir


def _safe(label: str, fn: Callable[[], Any]) -> bool:
    """Run fn(), printing success or a warning. Returns True on success."""
    try:
        fn()
        print(f"  + {label}")
        return True
    except Exception as exc:
        print(f"  ! {label}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Resource deletion helpers
# ---------------------------------------------------------------------------

def _delete_codedeploy(session: boto3.Session, backend: dict[str, Any]) -> None:
    cd = session.client("codedeploy")
    iam = session.client("iam")
    app_names: set[str] = set()
    service_role_deleted: set[str] = set()

    for stage_name in ("production", "staging"):
        stage = backend.get(stage_name)
        if not isinstance(stage, dict):
            continue
        app = stage.get("codedeploy_application", "")
        group = stage.get("codedeploy_deployment_group", "")
        if app and group:
            _safe(
                f"Delete CodeDeploy deployment group {group}",
                lambda a=app, g=group: cd.delete_deployment_group(
                    applicationName=a, deploymentGroupName=g
                ),
            )
        if app:
            app_names.add(app)
        service_role_arn = stage.get("codedeploy_service_role_arn", "")
        if service_role_arn and service_role_arn not in service_role_deleted:
            role_name = service_role_arn.split("/")[-1]

            def _del_cd_role(rn: str = role_name) -> None:
                attached = iam.list_attached_role_policies(RoleName=rn).get("AttachedPolicies", [])
                for p in attached:
                    iam.detach_role_policy(RoleName=rn, PolicyArn=p["PolicyArn"])
                iam.delete_role(RoleName=rn)

            _safe(f"Delete CodeDeploy service role {role_name}", _del_cd_role)
            service_role_deleted.add(service_role_arn)

    for app in app_names:
        _safe(
            f"Delete CodeDeploy application {app}",
            lambda a=app: cd.delete_application(applicationName=a),
        )


def _delete_lambdas(session: boto3.Session, backend: dict[str, Any]) -> None:
    lmb = session.client("lambda")
    for stage_name in ("production", "staging"):
        stage = backend.get(stage_name)
        if not isinstance(stage, dict):
            continue
        fn_name = stage.get("lambda_function_name", "")
        if fn_name:
            _safe(
                f"Delete Lambda {fn_name}",
                lambda n=fn_name: lmb.delete_function(FunctionName=n),
            )


def _delete_lambda_log_groups(
    session: boto3.Session, backend: dict[str, Any], keep_logs: bool
) -> None:
    if keep_logs:
        print("  - Skipping Lambda CloudWatch log groups (--keep-logs)")
        return
    logs = session.client("logs")
    for stage_name in ("production", "staging"):
        stage = backend.get(stage_name)
        if not isinstance(stage, dict):
            continue
        fn_name = stage.get("lambda_function_name", "")
        if not fn_name:
            continue
        lg_name = f"/aws/lambda/{fn_name}"

        def _del_lg(name: str = lg_name) -> None:
            logs.delete_log_group(logGroupName=name)

        _safe(f"Delete CloudWatch log group {lg_name}", _del_lg)


def _delete_rest_apis(session: boto3.Session, backend: dict[str, Any]) -> None:
    apigw = session.client("apigateway")
    for stage_name in ("production", "staging"):
        stage = backend.get(stage_name)
        if not isinstance(stage, dict):
            continue
        api_id = stage.get("rest_api_id", "")
        if api_id:
            _safe(
                f"Delete REST API Gateway {api_id}",
                lambda aid=api_id: apigw.delete_rest_api(restApiId=aid),
            )


def _delete_websocket_apis(session: boto3.Session, backend: dict[str, Any]) -> None:
    apigwv2 = session.client("apigatewayv2")
    for stage_name in ("production", "staging"):
        stage = backend.get(stage_name)
        if not isinstance(stage, dict):
            continue
        api_id = stage.get("websocket_api_id", "")
        if api_id:
            _safe(
                f"Delete WebSocket API Gateway {api_id}",
                lambda aid=api_id: apigwv2.delete_api(ApiId=aid),
            )


def _delete_ecr(session: boto3.Session, backend: dict[str, Any]) -> None:
    ecr = session.client("ecr")
    ecr_info = backend.get("ecr")
    if not isinstance(ecr_info, dict):
        return
    repo_name = ecr_info.get("repository_name", "")
    if repo_name:
        _safe(
            f"Delete ECR repository {repo_name}",
            lambda n=repo_name: ecr.delete_repository(repositoryName=n, force=True),
        )


def _delete_iam_resources(session: boto3.Session, iam_data: dict[str, Any]) -> None:
    iam = session.client("iam")
    role_name = iam_data.get("role_name", "")
    policy_arn = iam_data.get("policy_arn", "")

    if role_name:
        def _del_role(rn: str = role_name) -> None:
            attached = iam.list_attached_role_policies(RoleName=rn).get("AttachedPolicies", [])
            for p in attached:
                iam.detach_role_policy(RoleName=rn, PolicyArn=p["PolicyArn"])
            iam.delete_role(RoleName=rn)
        _safe(f"Delete IAM role {role_name}", _del_role)

    if policy_arn:
        def _del_policy(pa: str = policy_arn) -> None:
            versions = iam.list_policy_versions(PolicyArn=pa).get("Versions", [])
            for v in versions:
                if not v.get("IsDefaultVersion"):
                    iam.delete_policy_version(PolicyArn=pa, VersionId=v["VersionId"])
            iam.delete_policy(PolicyArn=pa)
        _safe(f"Delete IAM policy {policy_arn}", _del_policy)


def _delete_s3(session: boto3.Session, s3_data: dict[str, Any]) -> None:
    bucket_name = s3_data.get("bucket_name", "")
    created = s3_data.get("created", False)
    if not bucket_name:
        return
    if not created:
        print(f"  - Skipping S3 bucket {bucket_name} (pre-existing, not created by deploy)")
        return

    s3 = session.client("s3")

    def _empty_and_delete(bn: str = bucket_name) -> None:
        try:
            versioning = s3.get_bucket_versioning(Bucket=bn).get("Status", "")
        except Exception:
            versioning = ""
        if versioning in ("Enabled", "Suspended"):
            paginator = s3.get_paginator("list_object_versions")
            for page in paginator.paginate(Bucket=bn):
                delete_list = [
                    {"Key": o["Key"], "VersionId": o["VersionId"]}
                    for o in page.get("Versions", []) + page.get("DeleteMarkers", [])
                ]
                if delete_list:
                    s3.delete_objects(Bucket=bn, Delete={"Objects": delete_list})
        else:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bn):
                delete_list = [{"Key": o["Key"]} for o in page.get("Contents", [])]
                if delete_list:
                    s3.delete_objects(Bucket=bn, Delete={"Objects": delete_list})
        s3.delete_bucket(Bucket=bn)

    _safe(f"Empty and delete S3 bucket {bucket_name}", _empty_and_delete)


def _delete_cognito(session: boto3.Session, cognito_data: dict[str, Any]) -> None:
    user_pool_id = cognito_data.get("user_pool_id", "")
    if not user_pool_id:
        return
    idp = session.client("cognito-idp")
    _safe(
        f"Delete Cognito user pool {user_pool_id}",
        lambda pid=user_pool_id: idp.delete_user_pool(UserPoolId=pid),
    )


def _delete_dynamodb_tables(session: boto3.Session, dynamodb_data: dict[str, Any]) -> None:
    ddb = session.client("dynamodb")
    tables = dynamodb_data.get("tables", {})
    for table_name in tables:
        _safe(
            f"Delete DynamoDB table {table_name}",
            lambda tn=table_name: ddb.delete_table(TableName=tn),
        )


def _delete_github_oidc_roles(session: boto3.Session, oidc_data: dict[str, Any]) -> None:
    iam = session.client("iam")
    for field in ("production_role_arn", "staging_role_arn"):
        role_arn = oidc_data.get(field, "")
        if not role_arn:
            continue
        role_name = role_arn.split("/")[-1]
        account_id = role_arn.split(":")[4]
        policy_name = role_name.replace("Role-", "Policy-")
        policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"

        def _del_oidc_role(rn: str = role_name, pa: str = policy_arn) -> None:
            try:
                attached = iam.list_attached_role_policies(RoleName=rn).get("AttachedPolicies", [])
                for p in attached:
                    iam.detach_role_policy(RoleName=rn, PolicyArn=p["PolicyArn"])
                iam.delete_role(RoleName=rn)
            except iam.exceptions.NoSuchEntityException:
                pass
            try:
                versions = iam.list_policy_versions(PolicyArn=pa).get("Versions", [])
                for v in versions:
                    if not v.get("IsDefaultVersion"):
                        iam.delete_policy_version(PolicyArn=pa, VersionId=v["VersionId"])
                iam.delete_policy(PolicyArn=pa)
            except iam.exceptions.NoSuchEntityException:
                pass

        _safe(f"Delete GitHub OIDC role {role_name}", _del_oidc_role)


# ---------------------------------------------------------------------------
# Main teardown orchestration
# ---------------------------------------------------------------------------

def teardown_environment(
    env_name: str,
    aws_profile: str,
    aws_region: str,
    skip_tables: bool = False,
    skip_cognito: bool = False,
    keep_logs: bool = False,
) -> None:
    manifest, state_dir = _load_manifest(env_name, aws_region)
    region = manifest.get("aws_region") or aws_region
    session = _session(aws_profile, region)

    backend = manifest.get("backend", {})
    iam_data = manifest.get("iam", {})
    s3_data = manifest.get("s3", {})
    cognito_data = manifest.get("cognito", {})
    dynamodb_data = manifest.get("dynamodb", {})
    oidc_data = manifest.get("github_oidc", {})

    print(f"\nTearing down environment: {env_name} (region: {region})")
    print("=" * 60)

    print("\n[1/9] CodeDeploy (deployment groups + application)")
    _delete_codedeploy(session, backend)

    print("\n[2/9] Lambda functions")
    _delete_lambdas(session, backend)

    print("\n[3/9] Lambda CloudWatch log groups")
    _delete_lambda_log_groups(session, backend, keep_logs)

    print("\n[4/9] REST API Gateways")
    _delete_rest_apis(session, backend)

    print("\n[5/9] WebSocket API Gateways")
    _delete_websocket_apis(session, backend)

    print("\n[6/9] ECR repository")
    _delete_ecr(session, backend)

    print("\n[7/9] IAM role + policy")
    _delete_iam_resources(session, iam_data)

    print("\n[8/9] S3 bucket")
    _delete_s3(session, s3_data)

    if not skip_cognito:
        print("\n[9a/9] Cognito user pool")
        _delete_cognito(session, cognito_data)
    else:
        print("\n[9a/9] Cognito user pool — SKIPPED (--skip-cognito)")

    if not skip_tables:
        print("\n[9b/9] DynamoDB tables")
        _delete_dynamodb_tables(session, dynamodb_data)
    else:
        print("\n[9b/9] DynamoDB tables — SKIPPED (--skip-tables)")

    print("\n[+] GitHub OIDC deploy roles")
    _delete_github_oidc_roles(session, oidc_data)

    print(f"\nRemoving local state directory: {state_dir}")
    try:
        shutil.rmtree(state_dir)
        print(f"  + Removed {state_dir}")
    except Exception as exc:
        print(f"  ! Could not remove state dir: {exc}")

    print(f"\nTeardown complete for environment: {env_name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tear down all AWS resources created by deploy_environment.py"
    )
    parser.add_argument("environment_name", help="Environment name to tear down (e.g. arbitiumrs)")
    parser.add_argument("--aws-profile", required=True, help="AWS profile to use")
    parser.add_argument("--aws-region", default="us-east-1", help="AWS region")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm teardown without interactive prompt",
    )
    parser.add_argument(
        "--skip-tables",
        action="store_true",
        help="Skip DynamoDB table deletion (preserves data)",
    )
    parser.add_argument(
        "--skip-cognito",
        action="store_true",
        help="Skip Cognito user pool deletion (preserves users)",
    )
    parser.add_argument(
        "--keep-logs",
        action="store_true",
        help="Do not delete /aws/lambda/<function> CloudWatch log groups for backend Lambdas",
    )
    args = parser.parse_args()

    if not args.yes:
        print(f"\nThis will DELETE all AWS resources for environment '{args.environment_name}'.")
        if args.skip_tables:
            print("  DynamoDB tables will be preserved (--skip-tables).")
        if args.skip_cognito:
            print("  Cognito user pool will be preserved (--skip-cognito).")
        if args.keep_logs:
            print("  Lambda CloudWatch log groups will be preserved (--keep-logs).")
        confirm = input("\nType the environment name to confirm: ").strip()
        if confirm != args.environment_name:
            print("Aborted.")
            return

    try:
        teardown_environment(
            env_name=args.environment_name,
            aws_profile=args.aws_profile,
            aws_region=args.aws_region,
            skip_tables=args.skip_tables,
            skip_cognito=args.skip_cognito,
            keep_logs=args.keep_logs,
        )
    except FileNotFoundError as exc:
        # Idempotent: re-run uninstall after launcher state was already removed.
        print(f"\n{exc}")
        print("Launcher teardown skipped — nothing to do (already torn down or never deployed here).")
        raise SystemExit(0)
    except Exception as exc:
        print(f"\nTeardown failed: {exc}")
        raise


if __name__ == "__main__":
    main()
