"""Write GitHub environment payload JSON files for production/staging."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


# Optional bootstrap/state/<env>/vars.json template for VARS; ECS block intentionally omitted.
_APP_VARS_KEY_ORDER = [
    "WL_NAME",
    "BASE_URL",
    "WEBSOCKET_CONNECTIONS",
    "WEBSOCKET_URL",
    "API_GATEWAY_ARN",
    "LAMBDA_BACKEND_ARN",
    "LAMBDA_EXTERNAL_HANDLERS_ARN",
    "ROLE_ARN",
    "DYNAMODB_ENTITY_TABLE",
    "DYNAMODB_BLUEPRINT_TABLE",
    "DYNAMODB_RINGDATA_TABLE",
    "DYNAMODB_REL_TABLE",
    "DYNAMODB_CHAT_TABLE",
    "DYNAMODB_SESSION_TABLE",
    "DYNAMODB_SEARCH_TABLE",
    "COGNITO_REGION",
    "COGNITO_USERPOOL_ID",
    "COGNITO_APP_CLIENT_ID",
    "COGNITO_CHECK_TOKEN_EXPIRATION",
    "PREVIEW_LAYER",
    "S3_BUCKET_NAME",
    "ALLOW_DEV_ORIGINS",
    "CODEDEPLOY_APPLICATION_NAME",
    "CODEDEPLOY_DEPLOYMENT_GROUP_NAME",
    "CODEDEPLOY_DEPLOYMENT_CONFIG_NAME",
]

_BOOTSTRAP_VAR_KEY_ORDER = ["AWS_REGION", "AWS_DEFAULT_REGION", "AWS_ECR_REPOSITORY"]


def _websocket_vars_from_stage(stage_backend: Mapping[str, Any]) -> dict[str, str]:
    """
  Per-stage WebSocket URLs from provision_backend_infra / create_websocket_api.
  WEBSOCKET_CONNECTIONS = https management API base (post_to_connection).
  WEBSOCKET_URL = wss client URL.
  """
    ws = stage_backend.get("websocket") or {}
    if not isinstance(ws, dict):
        return {}
    connections = str(ws.get("connections_url") or "").strip()
    wss_url = str(ws.get("websocket_url") or "").strip()
    out: dict[str, str] = {}
    if connections:
        out["WEBSOCKET_CONNECTIONS"] = connections.rstrip("/")
    if wss_url:
        out["WEBSOCKET_URL"] = wss_url.rstrip("/")
    return out


def _codedeploy_var_values(
    env_name: str, stage_backend: Mapping[str, Any], stage_name: str
) -> tuple[str, str, str]:
    cd = stage_backend.get("codedeploy")
    if not isinstance(cd, dict):
        cd = {}
    app = str(cd.get("application_name") or "").strip() or f"{env_name}-backend-codedeploy"
    group = str(cd.get("deployment_group_name") or "").strip() or f"{env_name}-backend-{stage_name}"
    config = str(cd.get("deployment_config_name") or "").strip()
    if not config:
        config = (
            "CodeDeployDefault.LambdaCanary10Percent10Minutes"
            if stage_name == "production"
            else "CodeDeployDefault.LambdaAllAtOnce"
        )
    return app, group, config


def _app_vars_from_deploy(
    *,
    env_name: str,
    aws_region: str,
    cognito: Mapping[str, Any],
    iam_role_arn: str,
    s3_bucket_name: str,
    account_id: str,
    stage_backend: Mapping[str, Any],
    stage_name: str,
) -> dict[str, str]:
    rest = stage_backend.get("rest_api") or {}
    api_id = str(rest.get("api_id", "") or "").strip()
    invoke_url = str(rest.get("invoke_url", "") or "").strip()
    lambda_info = stage_backend.get("lambda") or {}
    lambda_backend_arn = str(lambda_info.get("function_arn", "") or "").strip()

    api_gw_arn = ""
    if api_id and account_id:
        api_gw_arn = f"arn:aws:execute-api:{aws_region}:{account_id}:{api_id}/*"

    cd_app, cd_group, cd_config = _codedeploy_var_values(env_name, stage_backend, stage_name)

    vars_out = {
        "WL_NAME": env_name,
        "BASE_URL": invoke_url,
        "API_GATEWAY_ARN": api_gw_arn,
        "LAMBDA_BACKEND_ARN": lambda_backend_arn,
        "ROLE_ARN": iam_role_arn,
        "DYNAMODB_ENTITY_TABLE": f"{env_name}_entities",
        "DYNAMODB_BLUEPRINT_TABLE": f"{env_name}_blueprints",
        "DYNAMODB_RINGDATA_TABLE": f"{env_name}_data",
        "DYNAMODB_REL_TABLE": f"{env_name}_rel",
        "DYNAMODB_CHAT_TABLE": f"{env_name}_chat",
        "DYNAMODB_SESSION_TABLE": f"{env_name}_session",
        "DYNAMODB_SEARCH_TABLE": f"{env_name}_search",
        "COGNITO_REGION": aws_region,
        "COGNITO_USERPOOL_ID": str(cognito.get("user_pool_id", "")),
        "COGNITO_APP_CLIENT_ID": str(cognito.get("app_client_id", "")),
        "COGNITO_CHECK_TOKEN_EXPIRATION": "True",
        "PREVIEW_LAYER": "2",
        "S3_BUCKET_NAME": s3_bucket_name,
        "ALLOW_DEV_ORIGINS": "true",
        "CODEDEPLOY_APPLICATION_NAME": cd_app,
        "CODEDEPLOY_DEPLOYMENT_GROUP_NAME": cd_group,
        "CODEDEPLOY_DEPLOYMENT_CONFIG_NAME": cd_config,
    }
    vars_out.update(_websocket_vars_from_stage(stage_backend))
    return vars_out


def _merge_overrides(app_vars: dict[str, str], overrides: Mapping[str, str] | None) -> None:
    if not overrides:
        return
    allowed = set(_APP_VARS_KEY_ORDER)
    for k, v in overrides.items():
        if k in allowed:
            app_vars[k] = str(v)


def merge_app_vars_from_vars_json_example(
    bootstrap_state_dir: Path | None, app_vars: dict[str, str]
) -> None:
    """
    Optionally fill empty VARS entries from bootstrap/state/<env>/vars.json
    (same shape as inject_github_env_vars). Does not overwrite non-empty deploy
    values — so staging/production BASE_URL REST URLs stay distinct.
    ECS keys present in vars.json but not listed in _APP_VARS_KEY_ORDER are ignored.
    """
    if bootstrap_state_dir is None:
        return

    example = bootstrap_state_dir / "vars.json"
    if not example.exists():
        return
    try:
        raw = json.loads(example.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if not isinstance(raw, dict):
        return
    tmpl = raw.get("VARS") or {}
    if not isinstance(tmpl, dict):
        return
    allowed = set(_APP_VARS_KEY_ORDER)
    for k in allowed:
        if app_vars.get(k, "").strip():
            continue
        if k not in tmpl or tmpl[k] is None:
            continue
        app_vars[k] = str(tmpl[k])


def _ordered_vars_payload(app_vars: dict[str, str], bootstrap_payload: Mapping[str, Any]) -> dict[str, str]:
    merged: dict[str, str] = {k: app_vars.get(k, "") for k in _APP_VARS_KEY_ORDER}
    region = str(bootstrap_payload.get("region", "") or "").strip()
    merged["AWS_REGION"] = region
    merged["AWS_DEFAULT_REGION"] = region
    merged["AWS_ECR_REPOSITORY"] = str(bootstrap_payload.get("ecr_repository", "") or "")
    ordered: dict[str, str] = {}
    for k in _APP_VARS_KEY_ORDER:
        ordered[k] = merged[k]
    for k in _BOOTSTRAP_VAR_KEY_ORDER:
        ordered[k] = merged[k]
    return ordered


def write_environment_jsons(
    output_dir: Path,
    *,
    bootstrap_state_dir: Path | None = None,
    bootstrap: Mapping[str, Any],
    github_repo: str,
    env_name: str,
    aws_region: str,
    cognito: Mapping[str, Any],
    iam_role_arn: str,
    s3_bucket_name: str,
    backend_by_stage: Mapping[str, Mapping[str, Any]],
    app_var_overrides: Mapping[str, str] | None = None,
    merge_launcher_example_vars_json: bool = True,
) -> dict[str, Path]:
    """Write production.json / staging.json (GITHUB_REPOSITORY, VARS, SECRETS) to output_dir."""

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    role_by_environment = {
        "production": str(bootstrap.get("role_arn_production", "") or ""),
        "staging": str(bootstrap.get("role_arn_staging", "") or ""),
    }
    account_id = str(bootstrap.get("account_id", "") or "")

    for environment, role_arn in role_by_environment.items():
        if not role_arn.strip():
            continue
        stage_backend = backend_by_stage.get(environment) or {}
        app_vars = _app_vars_from_deploy(
            env_name=env_name,
            aws_region=aws_region,
            cognito=cognito,
            iam_role_arn=iam_role_arn,
            s3_bucket_name=s3_bucket_name,
            account_id=account_id,
            stage_backend=stage_backend if isinstance(stage_backend, dict) else {},
            stage_name=environment,
        )
        if merge_launcher_example_vars_json:
            merge_app_vars_from_vars_json_example(bootstrap_state_dir, app_vars)
        _merge_overrides(app_vars, app_var_overrides)
        vars_payload = _ordered_vars_payload(app_vars, bootstrap)
        payload = {
            "GITHUB_REPOSITORY": str(github_repo).strip(),
            "ENVIRONMENT": environment,
            "VARS": vars_payload,
            "SECRETS": {
                "AWS_GITHUB_OIDC_ROLE_ARN": role_arn.strip(),
            },
        }
        path = output_dir / f"{environment}.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        outputs[environment] = path
    return outputs
