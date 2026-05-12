"""Write a plain-text and structured-JSON list of resources created/found during deploy."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_created_resources_txt(
    output_dir: Path,
    env_name: str,
    result: Mapping[str, Any],
) -> Path:
    """Write human-readable created_resources.txt to output_dir (launcher/state/<env>/)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "created_resources.txt"

    lines: list[str] = []
    lines.append(f"Environment: {env_name}")
    lines.append("")

    dynamodb = result.get("dynamodb_tables", {})
    if isinstance(dynamodb, dict):
        lines.append("DynamoDB Tables:")
        for name, arn in sorted(dynamodb.items()):
            lines.append(f"- {name}: {arn}")
        lines.append("")

    cognito = result.get("cognito", {})
    if isinstance(cognito, dict):
        lines.append("Cognito:")
        lines.append(f"- user_pool_id: {cognito.get('user_pool_id', '')}")
        lines.append(f"- user_pool_arn: {cognito.get('user_pool_arn', '')}")
        lines.append(f"- app_client_id: {cognito.get('app_client_id', '')}")
        lines.append("")

    iam_policy = result.get("iam_policy", {})
    iam_role = result.get("iam_role", {})
    if isinstance(iam_policy, dict) or isinstance(iam_role, dict):
        lines.append("IAM:")
        if isinstance(iam_policy, dict):
            lines.append(f"- policy_name: {iam_policy.get('policy_name', '')}")
            lines.append(f"- policy_arn: {iam_policy.get('policy_arn', '')}")
        if isinstance(iam_role, dict):
            lines.append(f"- role_name: {iam_role.get('role_name', '')}")
            lines.append(f"- role_arn: {iam_role.get('role_arn', '')}")
        lines.append("")

    s3 = result.get("s3", {})
    if isinstance(s3, dict):
        lines.append("S3:")
        lines.append(f"- bucket_name: {s3.get('bucket_name', '')}")
        lines.append(f"- bucket_arn: {s3.get('bucket_arn', '')}")
        lines.append(f"- created: {s3.get('created', '')}")
        lines.append("")

    backend = result.get("backend", {})
    if isinstance(backend, dict):
        lines.append("Backend Infra:")
        stage_backends: list[tuple[str, dict[str, Any]]] = []
        for stage_name in ("production", "staging"):
            value = backend.get(stage_name)
            if isinstance(value, dict):
                stage_backends.append((stage_name, value))

        if stage_backends:
            for stage_name, stage_backend in stage_backends:
                lines.append(f"- stage: {stage_name}")
                ecr = stage_backend.get("ecr", {})
                if isinstance(ecr, dict):
                    lines.append(f"  ecr_repository: {ecr.get('repository_name', '')}")
                    lines.append(f"  ecr_repository_arn: {ecr.get('repository_arn', '')}")
                lambda_info = stage_backend.get("lambda", {})
                if isinstance(lambda_info, dict):
                    lines.append(f"  lambda_function_name: {lambda_info.get('function_name', '')}")
                    lines.append(f"  lambda_function_arn: {lambda_info.get('function_arn', '')}")
                alias_info = stage_backend.get("alias", {})
                if isinstance(alias_info, dict):
                    lines.append(f"  lambda_alias_name: {alias_info.get('alias_name', '')}")
                    lines.append(f"  lambda_alias_arn: {alias_info.get('alias_arn', '')}")
                ws = stage_backend.get("websocket", {})
                if isinstance(ws, dict):
                    lines.append(f"  websocket_url: {ws.get('websocket_url', '')}")
                    lines.append(f"  websocket_connections: {ws.get('connections_url', '')}")
                codedeploy = stage_backend.get("codedeploy", {})
                if isinstance(codedeploy, dict):
                    lines.append(f"  codedeploy_application: {codedeploy.get('application_name', '')}")
                    lines.append(f"  codedeploy_deployment_group: {codedeploy.get('deployment_group_name', '')}")
                    lines.append(f"  codedeploy_config: {codedeploy.get('deployment_config_name', '')}")
        else:
            ecr = backend.get("ecr", {})
            if isinstance(ecr, dict):
                lines.append(f"- ecr_repository: {ecr.get('repository_name', '')}")
                lines.append(f"- ecr_repository_arn: {ecr.get('repository_arn', '')}")
            lambda_info = backend.get("lambda", {})
            if isinstance(lambda_info, dict):
                lines.append(f"- lambda_function_name: {lambda_info.get('function_name', '')}")
                lines.append(f"- lambda_function_arn: {lambda_info.get('function_arn', '')}")
            alias_info = backend.get("alias", {})
            if isinstance(alias_info, dict):
                lines.append(f"- lambda_alias_name: {alias_info.get('alias_name', '')}")
                lines.append(f"- lambda_alias_arn: {alias_info.get('alias_arn', '')}")
            ws = backend.get("websocket", {})
            if isinstance(ws, dict):
                lines.append(f"- websocket_url: {ws.get('websocket_url', '')}")
                lines.append(f"- websocket_connections: {ws.get('connections_url', '')}")
        lines.append("")

    env_config_path = result.get("env_config_path", "")
    environment_json_paths = result.get("environment_json_paths", {})
    if env_config_path:
        lines.append("Generated Files:")
        lines.append(f"- env_config.py: {env_config_path}")
        if isinstance(environment_json_paths, dict):
            for stage_name in ("production", "staging"):
                stage_path = environment_json_paths.get(stage_name, "")
                if stage_path:
                    lines.append(f"- {stage_name}.json: {stage_path}")
        lines.append("")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out_path


def write_created_resources_json(
    output_dir: Path,
    env_name: str,
    aws_region: str,
    result: Mapping[str, Any],
) -> Path:
    """Write structured created_resources.json to output_dir (launcher/state/<env>/)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "created_resources.json"

    bootstrap = result.get("bootstrap") or {}
    dynamodb = result.get("dynamodb_tables") or {}
    cognito = result.get("cognito") or {}
    iam_policy = result.get("iam_policy") or {}
    iam_role = result.get("iam_role") or {}
    s3 = result.get("s3") or {}
    backend = result.get("backend") or {}

    backend_json: dict[str, Any] = {}
    for stage_name in ("production", "staging"):
        sb = backend.get(stage_name)
        if isinstance(sb, dict) and "ecr" in sb:
            backend_json["ecr"] = {
                "repository_name": sb["ecr"].get("repository_name", ""),
                "repository_arn": sb["ecr"].get("repository_arn", ""),
            }
            break

    for stage_name in ("production", "staging"):
        sb = backend.get(stage_name)
        if not isinstance(sb, dict):
            continue
        stage_data: dict[str, Any] = {}
        lambda_info = sb.get("lambda") or {}
        stage_data["lambda_function_name"] = lambda_info.get("function_name", "")
        stage_data["lambda_function_arn"] = lambda_info.get("function_arn", "")
        alias_info = sb.get("alias") or {}
        stage_data["lambda_alias_name"] = alias_info.get("alias_name", "")
        stage_data["lambda_alias_arn"] = alias_info.get("alias_arn", "")
        rest_api = sb.get("rest_api") or {}
        stage_data["rest_api_id"] = rest_api.get("api_id", "")
        stage_data["rest_api_name"] = rest_api.get("api_name", "")
        stage_data["rest_api_invoke_url"] = rest_api.get("invoke_url", "")
        ws = sb.get("websocket") or {}
        stage_data["websocket_api_id"] = ws.get("api_id", "")
        stage_data["websocket_url"] = ws.get("websocket_url", "")
        stage_data["websocket_connections_url"] = ws.get("connections_url", "")
        cd = sb.get("codedeploy") or {}
        stage_data["codedeploy_application"] = cd.get("application_name", "")
        stage_data["codedeploy_deployment_group"] = cd.get("deployment_group_name", "")
        stage_data["codedeploy_config"] = cd.get("deployment_config_name", "")
        stage_data["codedeploy_service_role_arn"] = cd.get("service_role_arn", "")
        backend_json[stage_name] = stage_data

    payload: dict[str, Any] = {
        "environment": env_name,
        "aws_region": aws_region,
        "updated_at": _utc_now_iso(),
        "dynamodb": {
            "tables": dict(dynamodb) if isinstance(dynamodb, dict) else {},
        },
        "cognito": {
            "user_pool_id": cognito.get("user_pool_id", ""),
            "user_pool_arn": cognito.get("user_pool_arn", ""),
            "app_client_id": cognito.get("app_client_id", ""),
        },
        "iam": {
            "policy_name": iam_policy.get("policy_name", ""),
            "policy_arn": iam_policy.get("policy_arn", ""),
            "role_name": iam_role.get("role_name", ""),
            "role_arn": iam_role.get("role_arn", ""),
        },
        "s3": {
            "bucket_name": s3.get("bucket_name", ""),
            "bucket_arn": s3.get("bucket_arn", ""),
            "created": bool(s3.get("created", False)),
        },
        "backend": backend_json,
        "github_oidc": {
            "oidc_provider_arn": bootstrap.get("oidc_provider_arn", ""),
            "production_role_arn": bootstrap.get("role_arn_production", ""),
            "staging_role_arn": bootstrap.get("role_arn_staging", ""),
        },
    }

    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out_path

