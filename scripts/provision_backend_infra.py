"""One-time backend infrastructure provisioning for launcher."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess
from typing import Any, Optional

import boto3

import create_websocket_api


REGLO_DEPLOYMENT_DESCRIPTION = "Reglo Deployment"


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


def _ensure_ecr_repository(session: boto3.Session, repository_name: str, apply_changes: bool) -> dict[str, Any]:
    ecr = session.client("ecr")
    try:
        repo = ecr.describe_repositories(repositoryNames=[repository_name])["repositories"][0]
        return {"repository_name": repository_name, "repository_arn": repo.get("repositoryArn", ""), "created": False}
    except ecr.exceptions.RepositoryNotFoundException:
        if not apply_changes:
            return {"repository_name": repository_name, "repository_arn": "", "created": True}
        repo = ecr.create_repository(repositoryName=repository_name)["repository"]
        return {"repository_name": repository_name, "repository_arn": repo.get("repositoryArn", ""), "created": True}


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
    function_arn: str,
    function_name: str,
    apply_changes: bool,
) -> dict[str, Any]:
    apigw = session.client("apigateway")
    lambda_client = session.client("lambda")

    def ensure_chat_resource_and_method(api_id: str) -> None:
        resources = apigw.get_resources(restApiId=api_id, limit=500).get("items", [])
        root_id = next((r["id"] for r in resources if r.get("path") == "/"), "")
        if not root_id:
            return

        chat_resource = next((r for r in resources if r.get("pathPart") == "_chat"), None)
        if chat_resource is None and apply_changes:
            chat_resource = apigw.create_resource(restApiId=api_id, parentId=root_id, pathPart="_chat")
        elif chat_resource is None:
            return

        message_resource = next((r for r in resources if r.get("pathPart") == "message"), None)
        if message_resource is None and apply_changes:
            message_resource = apigw.create_resource(
                restApiId=api_id,
                parentId=chat_resource["id"],
                pathPart="message",
            )
        elif message_resource is None:
            return

        resource_id = message_resource["id"]
        if apply_changes:
            try:
                apigw.put_method(
                    restApiId=api_id,
                    resourceId=resource_id,
                    httpMethod="POST",
                    authorizationType="NONE",
                )
            except apigw.exceptions.ConflictException:
                pass

            integration_uri = (
                f"arn:aws:apigateway:{region}:lambda:path/2015-03-31/functions/{function_arn}/invocations"
            )
            apigw.put_integration(
                restApiId=api_id,
                resourceId=resource_id,
                httpMethod="POST",
                type="AWS_PROXY",
                integrationHttpMethod="POST",
                uri=integration_uri,
                passthroughBehavior="WHEN_NO_MATCH",
            )
            source_arn = f"arn:aws:execute-api:{region}:{session.client('sts').get_caller_identity()['Account']}:{api_id}/*/POST/_chat/message"
            statement_id = f"{function_name}-rest-apigw"
            try:
                lambda_client.add_permission(
                    FunctionName=function_name,
                    StatementId=statement_id,
                    Action="lambda:InvokeFunction",
                    Principal="apigateway.amazonaws.com",
                    SourceArn=source_arn,
                )
            except lambda_client.exceptions.ResourceConflictException:
                pass
            apigw.create_deployment(restApiId=api_id, stageName=stage_name, description=REGLO_DEPLOYMENT_DESCRIPTION)

    existing = apigw.get_rest_apis(limit=500).get("items", [])
    for api in existing:
        if api.get("name") == api_name:
            api_id = api.get("id", "")
            ensure_chat_resource_and_method(api_id)
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
    ensure_chat_resource_and_method(api_id)
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
    rest_result = _ensure_rest_api(
        session,
        api_name=rest_api_name,
        region=config.aws_region,
        stage_name=config.stage_name,
        function_arn=lambda_result.get("function_arn", ""),
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
        )

    return {
        "ecr": ecr_result,
        "lambda": lambda_result,
        "rest_api": rest_result,
        "websocket": websocket_result,
    }
