import argparse
import json
import re
from typing import Any, Dict, Optional

import boto3


def get_aws_account_id(session):
    """Retrieve the AWS account number dynamically."""
    sts_client = session.client("sts")
    return sts_client.get_caller_identity()["Account"]


def _default_bucket_name(env_name: str, aws_account_id: str, aws_region: str) -> str:
    return f"{env_name}-{aws_account_id}-{aws_region}".lower()


def _extract_s3_bucket_name_from_policy_document(document: Any) -> Optional[str]:
    """Parse bucket name from any S3 ARN in the policy (object or bucket ARN)."""
    if document is None:
        return None
    if isinstance(document, str):
        document = json.loads(document)
    for stmt in document.get("Statement", []):
        res = stmt.get("Resource")
        resources = res if isinstance(res, list) else [res]
        for u in resources:
            if not isinstance(u, str) or ":s3:::" not in u:
                continue
            m = re.match(r"arn:aws:s3:::([^/*]+)", u)
            if m:
                return m.group(1)
    return None


def _policy_json_equal(a: Any, b: Any) -> bool:
    if isinstance(a, str):
        a = json.loads(a)
    if isinstance(b, str):
        b = json.loads(b)
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _build_tt_runtime_policy_document(
    env_name: str,
    aws_region: str,
    aws_account_id: str,
    cognito_user_pool_id: str,
    s3_bucket_name: str,
) -> dict:
    """Runtime policy for {env}_tt_role: actions unchanged from legacy; resources tightened where possible."""
    role_tt = f"{env_name}_tt_role"
    pass_role_arn = f"arn:aws:iam::{aws_account_id}:role/{role_tt}"
    lambda_prefix = f"arn:aws:lambda:{aws_region}:{aws_account_id}:function:{env_name}"
    log_group_arn = (
        f"arn:aws:logs:{aws_region}:{aws_account_id}:log-group:/aws/lambda/{env_name}*"
    )
    log_stream_arn = (
        f"arn:aws:logs:{aws_region}:{aws_account_id}:log-group:/aws/lambda/{env_name}*"
        ":log-stream:*"
    )

    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction"],
                "Resource": [
                    f"{lambda_prefix}*",
                    f"{lambda_prefix}*:*",
                ],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "apigateway:POST",
                    "apigateway:GET",
                    "apigateway:PUT",
                    "apigateway:DELETE",
                ],
                "Resource": [
                    f"arn:aws:apigateway:{aws_region}::/restapis/*",
                    f"arn:aws:apigateway:{aws_region}::/apis/*",
                ],
            },
            {
                "Sid": "S3ListEnvBucket",
                "Effect": "Allow",
                "Action": "s3:ListBucket",
                "Resource": [
                    f"arn:aws:s3:::{s3_bucket_name}",
                    f"arn:aws:s3:::{env_name}-*",
                ],
            },
            {
                "Sid": "S3ObjectsEnvBucket",
                "Effect": "Allow",
                "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
                "Resource": [
                    f"arn:aws:s3:::{s3_bucket_name}/*",
                    f"arn:aws:s3:::{env_name}-*/*",
                ],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": [log_group_arn, log_stream_arn],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                ],
                "Resource": [
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_blueprints",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_data",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_chat",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_chat/index/entity_index",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_session",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_entities",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_rel",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_data/index/path_index",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_*/index/*",
                ],
            },
            {
                "Effect": "Allow",
                "Action": "ses:SendEmail",
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "cognito-idp:ListUsers",
                    "cognito-idp:AdminCreateUser",
                    "cognito-idp:AdminSetUserPassword",
                    "cognito-idp:AdminInitiateAuth",
                    "cognito-idp:RespondToAuthChallenge",
                ],
                "Resource": f"arn:aws:cognito-idp:{aws_region}:{aws_account_id}:userpool/{cognito_user_pool_id}",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "events:PutRule",
                    "events:PutTargets",
                    "events:RemoveTargets",
                    "events:DeleteRule",
                    "events:ListRules",
                    "events:DescribeRule",
                    "events:ListTargetsByRule",
                ],
                "Resource": f"arn:aws:events:{aws_region}:{aws_account_id}:rule/{env_name}*",
            },
            {
                "Effect": "Allow",
                "Action": "events:PutEvents",
                "Resource": f"arn:aws:events:{aws_region}:{aws_account_id}:event-bus/default",
            },
            {
                "Effect": "Allow",
                "Action": "iam:PassRole",
                "Resource": pass_role_arn,
                "Condition": {
                    "StringEquals": {"iam:PassedToService": "events.amazonaws.com"},
                },
            },
            {
                "Effect": "Allow",
                "Action": ["execute-api:Invoke", "execute-api:ManageConnections"],
                "Resource": [
                    f"arn:aws:execute-api:{aws_region}:{aws_account_id}:*/*/POST/@connections/*",
                    f"arn:aws:execute-api:{aws_region}:{aws_account_id}:*/stage/POST/_schd/ping",
                ],
            },
            {
                "Effect": "Allow",
                "Action": "aoss:APIAccessAll",
                "Resource": "*",
            },
        ],
    }


def create_iam_policy(env_name, cognito_user_pool_id, aws_region, aws_profile, apply_changes: bool = True):
    """Creates an IAM policy with the specified environment name and Cognito User Pool ID."""

    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    iam_client = session.client("iam")

    aws_account_id = get_aws_account_id(session)
    policy_name = f"{env_name}_tt_policy"
    policy_arn = f"arn:aws:iam::{aws_account_id}:policy/{policy_name}"

    s3_bucket_name: Optional[str] = None
    current_document: Any = None
    policy_already_exists = False

    try:
        existing_policy = iam_client.get_policy(PolicyArn=policy_arn)
        policy_arn = existing_policy["Policy"]["Arn"]
        policy_already_exists = True

        policy_versions = iam_client.list_policy_versions(PolicyArn=policy_arn)
        current_version = next(
            (v for v in policy_versions["Versions"] if v["IsDefaultVersion"]), None
        )
        if current_version:
            current_policy = iam_client.get_policy_version(
                PolicyArn=policy_arn, VersionId=current_version["VersionId"]
            )
            current_document = current_policy["PolicyVersion"]["Document"]
            s3_bucket_name = _extract_s3_bucket_name_from_policy_document(
                current_document
            )
    except iam_client.exceptions.NoSuchEntityException:
        pass

    if s3_bucket_name is None:
        if policy_already_exists:
            raise ValueError(
                f"IAM policy {policy_name!r} exists but no S3 bucket ARN could be parsed from it. "
                "Fix or delete the policy, then re-run."
            )
        s3_bucket_name = _default_bucket_name(env_name, aws_account_id, aws_region)

    policy_document = _build_tt_runtime_policy_document(
        env_name,
        aws_region,
        aws_account_id,
        cognito_user_pool_id,
        s3_bucket_name,
    )

    if not policy_already_exists:
        if not apply_changes:
            return policy_name, policy_arn, s3_bucket_name
        response = iam_client.create_policy(
            PolicyName=policy_name,
            PolicyDocument=json.dumps(policy_document),
        )
        policy_arn = response["Policy"]["Arn"]
        print(f"✅ IAM Policy Created Successfully!")
        print(f"🔹 Policy Name: {policy_name}")
        print(f"🔹 Policy ARN: {policy_arn}")
        return policy_name, policy_arn, s3_bucket_name

    if current_document is not None and _policy_json_equal(
        current_document, policy_document
    ):
        print(
            f"✅ IAM Policy '{policy_name}' already exists and is up to date. Skipping creation."
        )
        print(f"🔹 Policy Name: {policy_name}")
        print(f"🔹 Policy ARN: {policy_arn}")
        return policy_name, policy_arn, s3_bucket_name

    print(f"🔄 IAM Policy '{policy_name}' exists but needs updating. Creating new version...")
    if not apply_changes:
        return policy_name, policy_arn, s3_bucket_name
    iam_client.create_policy_version(
        PolicyArn=policy_arn,
        PolicyDocument=json.dumps(policy_document),
        SetAsDefault=True,
    )
    print(f"✅ IAM Policy '{policy_name}' updated successfully!")
    print(f"🔹 Policy Name: {policy_name}")
    print(f"🔹 Policy ARN: {policy_arn}")
    return policy_name, policy_arn, s3_bucket_name


def run(
    env_name: str,
    cognito_user_pool_id: str,
    aws_profile: str,
    aws_region: str,
    apply_changes: bool = True,
) -> Dict[str, str]:
    """Programmatic entry point that returns structured data"""
    policy_name, policy_arn, s3_bucket_name = create_iam_policy(
        env_name,
        cognito_user_pool_id,
        aws_region,
        aws_profile,
        apply_changes=apply_changes,
    )

    return {
        "policy_name": policy_name,
        "policy_arn": policy_arn,
        "s3_bucket_name": s3_bucket_name,
        "s3_bucket_arn": s3_bucket_name,
    }


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Create an IAM policy with Cognito and S3 permissions."
    )
    parser.add_argument(
        "environment_name",
        type=str,
        help="The environment name (e.g., dev, prod, test).",
    )
    parser.add_argument(
        "cognito_user_pool_id", type=str, help="The Cognito User Pool ID."
    )
    parser.add_argument(
        "--aws-region", type=str, required=True, help="AWS region (e.g., us-east-1)."
    )
    parser.add_argument(
        "--aws-profile",
        type=str,
        default="default",
        help="AWS profile to use (default: 'default').",
    )

    args = parser.parse_args()

    result = run(
        args.environment_name,
        args.cognito_user_pool_id,
        args.aws_region,
        args.aws_profile,
    )

    print("\n🎯 IAM Policy Created Successfully!\n")
    print(f"Policy Name: {result['policy_name']}")
    print(f"Policy ARN : {result['policy_arn']}")
    print(f"S3 Bucket : {result['s3_bucket_arn']}")


if __name__ == "__main__":
    main()
