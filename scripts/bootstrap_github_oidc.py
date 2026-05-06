"""Tenant bootstrap for GitHub OIDC deploy roles."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import ClientError


OIDC_URL = "https://token.actions.githubusercontent.com"
OIDC_THUMBPRINT = "6938fd4d98bab03faadb97b34396831e3780aea1"
REGLO_DEPLOYMENT_DESCRIPTION = "Reglo Deployment"


@dataclass
class BootstrapConfig:
    env_name: str
    aws_profile: str
    aws_region: str
    github_repo: str
    enable_staging_role: bool = False
    skip_cdk_bootstrap: bool = False
    apply_changes: bool = True


def _session(profile: str, region: str) -> boto3.Session:
    return boto3.Session(profile_name=profile, region_name=region)


def _oidc_provider_arn(account_id: str) -> str:
    return f"arn:aws:iam::{account_id}:oidc-provider/token.actions.githubusercontent.com"


def _build_trust_policy(oidc_provider_arn: str, github_repo: str, github_environment: str) -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Federated": oidc_provider_arn},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
                    "StringLike": {"token.actions.githubusercontent.com:sub": f"repo:{github_repo}:environment:{github_environment}"},
                },
            }
        ],
    }


def _build_permissions_policy(region: str, account_id: str, env_name: str) -> dict[str, Any]:
    ecr_repo_arn = f"arn:aws:ecr:{region}:{account_id}:repository/{env_name}_backend"
    lambda_arn = f"arn:aws:lambda:{region}:{account_id}:function:{env_name}-backend-*"
    rest_api_arn = f"arn:aws:apigateway:{region}::/restapis/*"
    ws_api_arn = f"arn:aws:apigateway:{region}::/apis/*"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadIdentity",
                "Effect": "Allow",
                "Action": ["sts:GetCallerIdentity"],
                "Resource": "*",
            },
            {
                "Sid": "EcrPushPullScoped",
                "Effect": "Allow",
                "Action": [
                    "ecr:BatchGetImage",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload",
                    "ecr:PutImage",
                    "ecr:DescribeRepositories",
                    "ecr:CreateRepository",
                ],
                "Resource": ecr_repo_arn,
            },
            {
                "Sid": "EcrAuthTokenGlobal",
                "Effect": "Allow",
                "Action": ["ecr:GetAuthorizationToken"],
                "Resource": "*",
            },
            {
                "Sid": "LambdaScoped",
                "Effect": "Allow",
                "Action": [
                    "lambda:CreateFunction",
                    "lambda:GetFunction",
                    "lambda:UpdateFunctionCode",
                    "lambda:PublishVersion",
                    "lambda:ListVersionsByFunction",
                    "lambda:CreateAlias",
                    "lambda:UpdateAlias",
                    "lambda:GetAlias",
                    "lambda:ListAliases",
                ],
                "Resource": lambda_arn,
            },
            {
                "Sid": "ApiGatewayManage",
                "Effect": "Allow",
                "Action": [
                    "apigateway:GET",
                    "apigateway:POST",
                    "apigateway:PATCH",
                ],
                "Resource": [rest_api_arn, ws_api_arn],
            },
            {
                "Sid": "CloudFormationAndCdkToolkit",
                "Effect": "Allow",
                "Action": [
                    "cloudformation:CreateStack",
                    "cloudformation:UpdateStack",
                    "cloudformation:DeleteStack",
                    "cloudformation:DescribeStacks",
                    "cloudformation:DescribeStackEvents",
                    "cloudformation:DescribeStackResources",
                    "cloudformation:GetTemplate",
                    "cloudformation:CreateChangeSet",
                    "cloudformation:ExecuteChangeSet",
                    "cloudformation:DeleteChangeSet",
                    "cloudformation:DescribeChangeSet",
                    "cloudformation:ListStackResources",
                    "s3:*",
                    "ssm:GetParameter",
                    "ssm:PutParameter",
                ],
                "Resource": "*",
            },
            {
                "Sid": "PassExecutionRole",
                "Effect": "Allow",
                "Action": ["iam:PassRole"],
                "Resource": f"arn:aws:iam::{account_id}:role/{env_name}*",
            },
        ],
    }


def _ensure_oidc_provider(iam, oidc_provider_arn: str, apply_changes: bool) -> None:
    try:
        iam.get_open_id_connect_provider(OpenIDConnectProviderArn=oidc_provider_arn)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise
        if apply_changes:
            iam.create_open_id_connect_provider(
                Url=OIDC_URL,
                ClientIDList=["sts.amazonaws.com"],
                ThumbprintList=[OIDC_THUMBPRINT],
            )


def _ensure_cdk_bootstrap(account_id: str, config: BootstrapConfig) -> None:
    if config.skip_cdk_bootstrap or not config.apply_changes:
        return
    cdk_executable = shutil.which("cdk") or shutil.which("cdk.cmd")
    if not cdk_executable:
        raise RuntimeError(
            "CDK CLI not found in PATH. Install aws-cdk globally or rerun with --skip-cdk-bootstrap."
        )
    subprocess.run(
        [
            cdk_executable,
            "bootstrap",
            f"aws://{account_id}/{config.aws_region}",
            "--profile",
            config.aws_profile,
        ],
        check=True,
    )


def _ensure_role_and_policy(
    iam,
    account_id: str,
    role_name: str,
    policy_name: str,
    trust_policy: dict[str, Any],
    permissions_policy: dict[str, Any],
    apply_changes: bool,
) -> str:
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"
    try:
        iam.get_role(RoleName=role_name)
        if apply_changes:
            iam.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=json.dumps(trust_policy),
            )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise
        if apply_changes:
            iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description=REGLO_DEPLOYMENT_DESCRIPTION,
            )

    try:
        iam.get_policy(PolicyArn=policy_arn)
        if apply_changes:
            versions = iam.list_policy_versions(PolicyArn=policy_arn)["Versions"]
            non_default = sorted([v for v in versions if not v.get("IsDefaultVersion")], key=lambda x: x["CreateDate"])
            if len(non_default) >= 4:
                iam.delete_policy_version(PolicyArn=policy_arn, VersionId=non_default[0]["VersionId"])
            iam.create_policy_version(
                PolicyArn=policy_arn,
                PolicyDocument=json.dumps(permissions_policy),
                SetAsDefault=True,
            )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise
        if apply_changes:
            iam.create_policy(
                PolicyName=policy_name,
                PolicyDocument=json.dumps(permissions_policy),
                Description=REGLO_DEPLOYMENT_DESCRIPTION,
            )

    if apply_changes:
        iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
    return role_arn


def run(config: BootstrapConfig) -> dict[str, Any]:
    session = _session(config.aws_profile, config.aws_region)
    sts = session.client("sts")
    iam = session.client("iam")
    account_id = sts.get_caller_identity()["Account"]
    oidc_provider_arn = _oidc_provider_arn(account_id)

    _ensure_oidc_provider(iam, oidc_provider_arn, config.apply_changes)
    _ensure_cdk_bootstrap(account_id, config)

    role_arn_production = _ensure_role_and_policy(
        iam=iam,
        account_id=account_id,
        role_name=f"GitHubActionsDeployRole-{config.env_name}-production",
        policy_name=f"GitHubActionsDeployPolicy-{config.env_name}-production",
        trust_policy=_build_trust_policy(oidc_provider_arn, config.github_repo, "production"),
        permissions_policy=_build_permissions_policy(config.aws_region, account_id, config.env_name),
        apply_changes=config.apply_changes,
    )

    role_arn_staging = ""
    if config.enable_staging_role:
        role_arn_staging = _ensure_role_and_policy(
            iam=iam,
            account_id=account_id,
            role_name=f"GitHubActionsDeployRole-{config.env_name}-staging",
            policy_name=f"GitHubActionsDeployPolicy-{config.env_name}-staging",
            trust_policy=_build_trust_policy(oidc_provider_arn, config.github_repo, "staging"),
            permissions_policy=_build_permissions_policy(config.aws_region, account_id, config.env_name),
            apply_changes=config.apply_changes,
        )

    return {
        "account_id": account_id,
        "aws_profile": config.aws_profile,
        "region": config.aws_region,
        "github_repo": config.github_repo,
        "oidc_provider_arn": oidc_provider_arn,
        "role_arn_production": role_arn_production,
        "role_arn_staging": role_arn_staging,
        "ecr_repository": f"{config.env_name}_backend",
        "apply_changes": config.apply_changes,
    }
