"""One-time backend infrastructure provisioning for launcher."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import shutil
import subprocess
import time
from typing import Any, Optional

import boto3

import create_websocket_api


REGLO_DEPLOYMENT_DESCRIPTION = "Reglo Deployment"
CODEDEPLOY_MANAGED_ROLE_POLICY_ARN = "arn:aws:iam::aws:policy/service-role/AWSCodeDeployRoleForLambda"
IAM_PROPAGATION_WAIT_SECONDS = 10
CODEDEPLOY_MAX_ROLE_RETRIES = 4


@dataclass
class BackendProvisionConfig:
    env_name: str
    aws_profile: str
    aws_region: str
    lambda_role_arn: str
    stage_name: str = "production"
    architecture: str = "x86_64"
    timeout_seconds: int = 30
    memory_mb: int = 512
    websocket_route: str = create_websocket_api.DEFAULT_ROUTE
    seed_image_uri: str = ""
    apply_changes: bool = True


def _session(profile: Optional[str], region: str) -> boto3.Session:
    if profile:
        return boto3.Session(profile_name=profile, region_name=region)
    return boto3.Session(region_name=region)


def _ecr_repository_name(env_name: str) -> str:
    return f"{env_name}_backend"


def _lambda_function_name(env_name: str, stage_name: str) -> str:
    return f"{env_name}-backend-{stage_name}"


def _rest_api_name(env_name: str, stage_name: str) -> str:
    return f"{env_name}-api-{stage_name}"


def _websocket_api_name(env_name: str, stage_name: str) -> str:
    return f"{env_name}-websocket-{stage_name}"


def _lambda_alias_name(stage_name: str) -> str:
    return stage_name


def _codedeploy_application_name(env_name: str) -> str:
    return f"{env_name}-backend-codedeploy"


def _codedeploy_deployment_group_name(env_name: str, stage_name: str) -> str:
    return f"{env_name}-backend-{stage_name}"


def _codedeploy_service_role_name(env_name: str) -> str:
    return f"{env_name}-codedeploy-lambda-role"


def _ecr_lambda_repository_policy(account_id: str, region: str) -> dict[str, Any]:
    """Allow Lambda to pull container images from this ECR repo (required for CreateFunction PackageType=Image)."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "LambdaECRImageRetrievalPolicy",
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": [
                    "ecr:BatchGetImage",
                    "ecr:DeleteRepositoryPolicy",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:GetRepositoryPolicy",
                    "ecr:SetRepositoryPolicy",
                ],
                "Condition": {
                    "StringLike": {
                        "aws:sourceArn": f"arn:aws:lambda:{region}:{account_id}:function:*",
                    }
                },
            }
        ],
    }


def _ensure_ecr_lambda_pull_policy(
    session: boto3.Session,
    repository_name: str,
    *,
    apply_changes: bool,
) -> None:
    if not apply_changes:
        return
    account_id = session.client("sts").get_caller_identity()["Account"]
    region = session.region_name or "us-east-1"
    ecr = session.client("ecr")
    policy_text = json.dumps(_ecr_lambda_repository_policy(account_id, region))
    try:
        ecr.set_repository_policy(repositoryName=repository_name, policyText=policy_text)
    except ecr.exceptions.RepositoryNotFoundException:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"Failed to set ECR repository policy on {repository_name!r} for Lambda image pull: {exc}"
        ) from exc


def _ensure_ecr_repository(session: boto3.Session, repository_name: str, apply_changes: bool) -> dict[str, Any]:
    ecr = session.client("ecr")
    created = False
    try:
        repo = ecr.describe_repositories(repositoryNames=[repository_name])["repositories"][0]
    except ecr.exceptions.RepositoryNotFoundException:
        if not apply_changes:
            return {"repository_name": repository_name, "repository_arn": "", "created": True}
        repo = ecr.create_repository(repositoryName=repository_name)["repository"]
        created = True
    _ensure_ecr_lambda_pull_policy(session, repository_name, apply_changes=apply_changes)
    return {"repository_name": repository_name, "repository_arn": repo.get("repositoryArn", ""), "created": created}


def _ensure_lambda_role_ready(session: boto3.Session, role_arn: str, apply_changes: bool) -> None:
    """Verify execution role exists and wait for IAM propagation before CreateFunction."""
    if not apply_changes:
        return
    role_name = role_arn.rsplit("/", 1)[-1]
    iam = session.client("iam")
    try:
        iam.get_role(RoleName=role_name)
    except iam.exceptions.NoSuchEntityException as exc:
        raise ValueError(
            f"Lambda execution role {role_name!r} does not exist. "
            f"Re-run deploy_environment.py so create_iam_role creates {role_name!r} "
            f"and attaches {role_name.replace('_tt_role', '_tt_policy')} before backend provisioning."
        ) from exc
    attached = iam.list_attached_role_policies(RoleName=role_name).get("AttachedPolicies", [])
    if not attached:
        raise ValueError(
            f"Lambda execution role {role_name!r} has no attached policies. "
            f"Re-run create_iam_policy + create_iam_role (or full deploy_environment.py)."
        )
    time.sleep(IAM_PROPAGATION_WAIT_SECONDS)


def _ensure_lambda_function(
    session: boto3.Session,
    *,
    function_name: str,
    role_arn: str,
    image_uri: str,
    architecture: str,
    timeout_seconds: int,
    memory_mb: int,
    apply_changes: bool,
) -> dict[str, Any]:
    client = session.client("lambda")
    try:
        config = client.get_function(FunctionName=function_name)["Configuration"]
        return {"function_name": function_name, "function_arn": config.get("FunctionArn", ""), "created": False}
    except client.exceptions.ResourceNotFoundException:
        if not apply_changes:
            return {"function_name": function_name, "function_arn": "", "created": True}
        if not image_uri.strip():
            raise ValueError("Lambda does not exist and no image URI is available for create_function.")
        _ensure_lambda_role_ready(session, role_arn, apply_changes=apply_changes)
        config = client.create_function(
            FunctionName=function_name,
            Role=role_arn,
            PackageType="Image",
            Code={"ImageUri": image_uri},
            Timeout=timeout_seconds,
            MemorySize=memory_mb,
            Architectures=[architecture],
            Publish=True,
            Description=REGLO_DEPLOYMENT_DESCRIPTION,
        )
        return {"function_name": function_name, "function_arn": config.get("FunctionArn", ""), "created": True}


def _lambda_exists(session: boto3.Session, function_name: str) -> bool:
    client = session.client("lambda")
    try:
        client.get_function(FunctionName=function_name)
        return True
    except client.exceptions.ResourceNotFoundException:
        return False


def _latest_published_version(client, function_name: str) -> str:
    paginator = client.get_paginator("list_versions_by_function")
    latest = 0
    for page in paginator.paginate(FunctionName=function_name):
        for item in page.get("Versions", []):
            version = item.get("Version", "")
            if version == "$LATEST":
                continue
            if version.isdigit():
                latest = max(latest, int(version))
    return str(latest) if latest else ""


def _ensure_lambda_alias(
    session: boto3.Session,
    *,
    function_name: str,
    alias_name: str,
    apply_changes: bool,
) -> dict[str, Any]:
    client = session.client("lambda")
    aliases = client.list_aliases(FunctionName=function_name).get("Aliases", [])
    existing = next((a for a in aliases if a.get("Name") == alias_name), None)
    if existing:
        return {
            "alias_name": alias_name,
            "alias_arn": existing.get("AliasArn", ""),
            "function_version": existing.get("FunctionVersion", ""),
            "created": False,
        }

    target_version = _latest_published_version(client, function_name)
    if not target_version and apply_changes:
        published = client.publish_version(
            FunctionName=function_name,
            Description=f"{REGLO_DEPLOYMENT_DESCRIPTION} alias seed",
        )
        target_version = published.get("Version", "")

    if not target_version:
        return {"alias_name": alias_name, "alias_arn": "", "function_version": "", "created": True}

    if not apply_changes:
        return {"alias_name": alias_name, "alias_arn": "", "function_version": target_version, "created": True}

    created = client.create_alias(
        FunctionName=function_name,
        Name=alias_name,
        FunctionVersion=target_version,
        Description=f"{REGLO_DEPLOYMENT_DESCRIPTION} {alias_name} traffic alias",
    )
    return {
        "alias_name": alias_name,
        "alias_arn": created.get("AliasArn", ""),
        "function_version": created.get("FunctionVersion", ""),
        "created": True,
    }


def _ensure_codedeploy_service_role(session: boto3.Session, env_name: str, apply_changes: bool) -> dict[str, Any]:
    iam = session.client("iam")
    account_id = session.client("sts").get_caller_identity()["Account"]
    role_name = _codedeploy_service_role_name(env_name)
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "codedeploy.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    created = False
    try:
        iam.get_role(RoleName=role_name)
        if apply_changes:
            iam.update_assume_role_policy(RoleName=role_name, PolicyDocument=json.dumps(trust_policy))
    except iam.exceptions.NoSuchEntityException:
        if not apply_changes:
            return {"role_name": role_name, "role_arn": role_arn, "created": True}
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=REGLO_DEPLOYMENT_DESCRIPTION,
        )
        created = True
        time.sleep(IAM_PROPAGATION_WAIT_SECONDS)

    if apply_changes:
        try:
            iam.attach_role_policy(RoleName=role_name, PolicyArn=CODEDEPLOY_MANAGED_ROLE_POLICY_ARN)
        except iam.exceptions.NoSuchEntityException:
            pass
        time.sleep(IAM_PROPAGATION_WAIT_SECONDS)

    return {"role_name": role_name, "role_arn": role_arn, "created": created}


def _codedeploy_config_for_stage(stage_name: str) -> str:
    if stage_name == "production":
        return "CodeDeployDefault.LambdaCanary10Percent10Minutes"
    return "CodeDeployDefault.LambdaAllAtOnce"


def _ensure_codedeploy(
    session: boto3.Session,
    *,
    env_name: str,
    stage_name: str,
    apply_changes: bool,
) -> dict[str, Any]:
    codedeploy = session.client("codedeploy")
    app_name = _codedeploy_application_name(env_name)
    group_name = _codedeploy_deployment_group_name(env_name, stage_name)
    deployment_config_name = _codedeploy_config_for_stage(stage_name)

    app_created = False
    try:
        codedeploy.get_application(applicationName=app_name)
    except codedeploy.exceptions.ApplicationDoesNotExistException:
        if apply_changes:
            codedeploy.create_application(applicationName=app_name, computePlatform="Lambda")
            app_created = True
        else:
            return {
                "application_name": app_name,
                "deployment_group_name": group_name,
                "deployment_config_name": deployment_config_name,
                "service_role_arn": "",
                "created": True,
            }

    service_role = _ensure_codedeploy_service_role(session, env_name, apply_changes)
    role_arn = service_role.get("role_arn", "")
    create_payload = {
        "applicationName": app_name,
        "deploymentGroupName": group_name,
        "serviceRoleArn": role_arn,
        "deploymentConfigName": deployment_config_name,
        "deploymentStyle": {
            "deploymentType": "BLUE_GREEN",
            "deploymentOption": "WITH_TRAFFIC_CONTROL",
        },
        "autoRollbackConfiguration": {"enabled": False},
        "triggerConfigurations": [],
    }
    update_payload = {
        "applicationName": app_name,
        "currentDeploymentGroupName": group_name,
        "serviceRoleArn": role_arn,
        "deploymentConfigName": deployment_config_name,
        "deploymentStyle": {
            "deploymentType": "BLUE_GREEN",
            "deploymentOption": "WITH_TRAFFIC_CONTROL",
        },
        "autoRollbackConfiguration": {"enabled": False},
        "triggerConfigurations": [],
    }

    group_created = False
    try:
        codedeploy.get_deployment_group(applicationName=app_name, deploymentGroupName=group_name)
        if apply_changes:
            codedeploy.update_deployment_group(**update_payload)
    except codedeploy.exceptions.DeploymentGroupDoesNotExistException:
        if apply_changes:
            for attempt in range(CODEDEPLOY_MAX_ROLE_RETRIES):
                try:
                    codedeploy.create_deployment_group(**create_payload)
                    group_created = True
                    break
                except codedeploy.exceptions.InvalidRoleException:
                    if attempt == CODEDEPLOY_MAX_ROLE_RETRIES - 1:
                        raise
                    time.sleep(IAM_PROPAGATION_WAIT_SECONDS * (attempt + 1))

    return {
        "application_name": app_name,
        "deployment_group_name": group_name,
        "deployment_config_name": deployment_config_name,
        "service_role_arn": role_arn,
        "created": app_created or group_created,
    }


def _build_and_push_seed_image(
    session: boto3.Session,
    repository_name: str,
    region: str,
    architecture: str,
    apply_changes: bool,
) -> str:
    account_id = session.client("sts").get_caller_identity()["Account"]
    registry = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
    image_uri = f"{registry}/{repository_name}:seed"
    if not apply_changes:
        return image_uri

    if os.name == "nt":
        docker_executable = shutil.which("docker") or shutil.which("docker.exe") or shutil.which("docker.cmd")
        if docker_executable and not docker_executable.lower().endswith(".exe"):
            docker_executable = shutil.which("docker.exe") or docker_executable
    else:
        docker_executable = shutil.which("docker")
    if not docker_executable:
        raise RuntimeError("Docker is required to build/push seed image but was not found in PATH.")

    ecr = session.client("ecr", region_name=region)
    token_data = ecr.get_authorization_token()["authorizationData"][0]
    password = token_data["authorizationToken"]
    endpoint = token_data["proxyEndpoint"]
    import base64

    decoded = base64.b64decode(password).decode("utf-8")
    _, pwd = decoded.split(":", 1)
    subprocess.run(
        [docker_executable, "login", "--username", "AWS", "--password-stdin", endpoint.replace("https://", "")],
        input=pwd,
        text=True,
        check=True,
    )

    seed_context = Path(__file__).resolve().parent / "backend" / "seed-image"
    dockerfile = seed_context / "Dockerfile"
    platform = "linux/amd64" if architecture == "x86_64" else "linux/arm64"
    buildx_executable = docker_executable
    try:
        subprocess.run([buildx_executable, "buildx", "version"], check=True, capture_output=True, text=True)
        subprocess.run(
            [
                buildx_executable,
                "buildx",
                "build",
                "--platform",
                platform,
                "--provenance=false",
                "--sbom=false",
                "-t",
                image_uri,
                "-f",
                str(dockerfile),
                "--push",
                str(seed_context),
            ],
            check=True,
        )
    except Exception:
        # Fallback for engines without buildx plugin.
        subprocess.run(
            [docker_executable, "build", "--platform", platform, "-t", image_uri, "-f", str(dockerfile), str(seed_context)],
            check=True,
        )
        subprocess.run([docker_executable, "push", image_uri], check=True)
    return image_uri


def _ensure_rest_api(
    session: boto3.Session,
    *,
    api_name: str,
    region: str,
    stage_name: str,
    alias_arn: str,
    alias_name: str,
    function_name: str,
    apply_changes: bool,
) -> dict[str, Any]:
    apigw = session.client("apigateway")
    lambda_client = session.client("lambda")

    def ensure_proxy_routes(api_id: str) -> None:
        resources = apigw.get_resources(restApiId=api_id, limit=500).get("items", [])
        root_id = next((r["id"] for r in resources if r.get("path") == "/"), "")
        if not root_id:
            return

        proxy_resource = next((r for r in resources if r.get("pathPart") == "{proxy+}"), None)
        if proxy_resource is None and apply_changes:
            proxy_resource = apigw.create_resource(restApiId=api_id, parentId=root_id, pathPart="{proxy+}")
        elif proxy_resource is None:
            return

        if apply_changes:
            integration_uri = f"arn:aws:apigateway:{region}:lambda:path/2015-03-31/functions/{alias_arn}/invocations"
            for resource_id in (root_id, proxy_resource["id"]):
                try:
                    apigw.put_method(
                        restApiId=api_id,
                        resourceId=resource_id,
                        httpMethod="ANY",
                        authorizationType="NONE",
                    )
                except apigw.exceptions.ConflictException:
                    pass

                apigw.put_integration(
                    restApiId=api_id,
                    resourceId=resource_id,
                    httpMethod="ANY",
                    type="AWS_PROXY",
                    integrationHttpMethod="POST",
                    uri=integration_uri,
                    passthroughBehavior="WHEN_NO_MATCH",
                )

            source_arn = (
                f"arn:aws:execute-api:{region}:{session.client('sts').get_caller_identity()['Account']}:"
                f"{api_id}/*/*"
            )
            statement_id = f"{function_name}-rest-apigw-any"
            try:
                lambda_client.add_permission(
                    FunctionName=function_name,
                    StatementId=statement_id,
                    Action="lambda:InvokeFunction",
                    Principal="apigateway.amazonaws.com",
                    SourceArn=source_arn,
                    Qualifier=alias_name,
                )
            except lambda_client.exceptions.ResourceConflictException:
                pass
            apigw.create_deployment(restApiId=api_id, stageName=stage_name, description=REGLO_DEPLOYMENT_DESCRIPTION)

    existing = apigw.get_rest_apis(limit=500).get("items", [])
    for api in existing:
        if api.get("name") == api_name:
            api_id = api.get("id", "")
            ensure_proxy_routes(api_id)
            return {
                "api_name": api_name,
                "api_id": api_id,
                "invoke_url": f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage_name}",
                "created": False,
            }
    if not apply_changes:
        return {"api_name": api_name, "api_id": "", "invoke_url": "", "created": True}
    api = apigw.create_rest_api(name=api_name, description=REGLO_DEPLOYMENT_DESCRIPTION)
    api_id = api["id"]
    ensure_proxy_routes(api_id)
    return {
        "api_name": api_name,
        "api_id": api_id,
        "invoke_url": f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage_name}",
        "created": True,
    }


def run(config: BackendProvisionConfig) -> dict[str, Any]:
    session = _session(config.aws_profile, config.aws_region)
    repository_name = _ecr_repository_name(config.env_name)
    function_name = _lambda_function_name(config.env_name, config.stage_name)
    rest_api_name = _rest_api_name(config.env_name, config.stage_name)
    websocket_name = _websocket_api_name(config.env_name, config.stage_name)
    alias_name = _lambda_alias_name(config.stage_name)

    ecr_result = _ensure_ecr_repository(session, repository_name, config.apply_changes)
    seed_image_uri = (config.seed_image_uri or "").strip()
    if not seed_image_uri and not _lambda_exists(session, function_name):
        seed_image_uri = _build_and_push_seed_image(
            session=session,
            repository_name=repository_name,
            region=config.aws_region,
            architecture=config.architecture,
            apply_changes=config.apply_changes,
        )
    lambda_result = _ensure_lambda_function(
        session,
        function_name=function_name,
        role_arn=config.lambda_role_arn,
        image_uri=seed_image_uri,
        architecture=config.architecture,
        timeout_seconds=config.timeout_seconds,
        memory_mb=config.memory_mb,
        apply_changes=config.apply_changes,
    )
    alias_result = _ensure_lambda_alias(
        session,
        function_name=function_name,
        alias_name=alias_name,
        apply_changes=config.apply_changes,
    )
    rest_result = _ensure_rest_api(
        session,
        api_name=rest_api_name,
        region=config.aws_region,
        stage_name=config.stage_name,
        alias_arn=alias_result.get("alias_arn", ""),
        alias_name=alias_name,
        function_name=function_name,
        apply_changes=config.apply_changes,
    )
    integration_target = f"{rest_result['invoke_url']}/_chat/message" if rest_result["invoke_url"] else ""
    websocket_result: dict[str, Any] = {}
    if integration_target:
        websocket_result = create_websocket_api.run(
            websocket_name,
            config.websocket_route,
            integration_target,
            config.stage_name,
            config.aws_profile,
            config.aws_region,
            apply_changes=config.apply_changes,
        )
    codedeploy_result = _ensure_codedeploy(
        session,
        env_name=config.env_name,
        stage_name=config.stage_name,
        apply_changes=config.apply_changes,
    )

    return {
        "ecr": ecr_result,
        "lambda": lambda_result,
        "alias": alias_result,
        "rest_api": rest_result,
        "websocket": websocket_result,
        "codedeploy": codedeploy_result,
    }
