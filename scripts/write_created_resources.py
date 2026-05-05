"""Write a plain-text list of resources created/found during deploy."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def write_created_resources_txt(
    launcher_root: Path,
    env_name: str,
    result: Mapping[str, Any],
) -> Path:
    out_path = launcher_root / f"{env_name}_created_resources.txt"

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
        ecr = backend.get("ecr", {})
        if isinstance(ecr, dict):
            lines.append(f"- ecr_repository: {ecr.get('repository_name', '')}")
            lines.append(f"- ecr_repository_arn: {ecr.get('repository_arn', '')}")
        lambda_info = backend.get("lambda", {})
        if isinstance(lambda_info, dict):
            lines.append(f"- lambda_function_name: {lambda_info.get('function_name', '')}")
            lines.append(f"- lambda_function_arn: {lambda_info.get('function_arn', '')}")
        ws = backend.get("websocket", {})
        if isinstance(ws, dict):
            lines.append(f"- websocket_url: {ws.get('websocket_url', '')}")
            lines.append(f"- websocket_connections: {ws.get('connections_url', '')}")
        lines.append("")

    env_config_path = result.get("env_config_path", "")
    extension_install_path = result.get("extension_install_path", "")
    if env_config_path:
        lines.append("Generated Files:")
        lines.append(f"- env_config.py: {env_config_path}")
        if extension_install_path:
            lines.append(f"- extension_install.json: {extension_install_path}")
        lines.append("")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out_path

