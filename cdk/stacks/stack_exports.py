"""Stable CloudFormation stack outputs for write_state and external tooling.

Nested constructs prefix output keys (e.g. StorageDataBucketName…). Re-export
here at the Stack scope so OutputKey matches the contract (DataBucketName, …).
"""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, Stack
from constructs import IConstruct


def _emit(stack: Stack, key: str, value: str) -> None:
    CfnOutput(stack, key, value=value)


def export_stack_a_outputs(
    stack: Stack,
    *,
    auth: IConstruct,
    storage: IConstruct,
    runtime: IConstruct,
    env_name: str,
    enable_staging: bool,
) -> None:
    _emit(stack, "UserPoolId", auth.user_pool_id)
    _emit(stack, "UserPoolArn", auth.user_pool_arn)
    _emit(stack, "AppClientId", auth.app_client_id)

    _emit(stack, "DataBucketName", storage.data_bucket.bucket_name)
    _emit(stack, "DataBucketArn", storage.data_bucket.bucket_arn)
    _emit(stack, "EnvName", env_name)

    _emit(stack, "BackendEcrRepoName", runtime.backend_repo.repository_name)
    _emit(stack, "BackendEcrRepoUri", runtime.backend_repo.repository_uri)
    _emit(stack, "TenantPolicyArn", runtime.tt_policy.managed_policy_arn)
    _emit(stack, "TenantRoleArn", runtime.tt_role.role_arn)
    _emit(stack, "CodeDeployAppName", runtime.cd_app.application_name)
    _emit(stack, "OidcProviderArn", runtime.oidc_provider.open_id_connect_provider_arn)
    _emit(stack, "OidcDeployRoleArnProduction", runtime.oidc_deploy_role_production.role_arn)
    if enable_staging and runtime.oidc_deploy_role_staging is not None:
        _emit(stack, "OidcDeployRoleArnStaging", runtime.oidc_deploy_role_staging.role_arn)


def export_stack_b_app_outputs(stack: Stack, app: IConstruct) -> None:
    prod: dict[str, str] = app.production
    _emit(stack, "BackendLambdaFunctionNameProduction", prod["fn_name"])
    _emit(stack, "BackendLambdaAliasArnProduction", prod["alias_arn"])
    _emit(stack, "BackendLambdaLogGroupNameProduction", prod["log_group_name"])
    _emit(stack, "RestApiUrlProduction", prod["rest_url"])
    _emit(stack, "WebSocketUrlProduction", prod["ws_url"])
    _emit(stack, "WebSocketConnectionsUrlProduction", prod["ws_connections"])
    _emit(stack, "BackendLambdaArchitecture", app.architecture)
    _emit(stack, "BackendLambdaExecutionRoleArn", app.exec_role_arn)

    staging: dict[str, str] | None = app.staging
    if staging is not None:
        _emit(stack, "BackendLambdaFunctionNameStaging", staging["fn_name"])
        _emit(stack, "BackendLambdaAliasArnStaging", staging["alias_arn"])
        _emit(stack, "BackendLambdaLogGroupNameStaging", staging["log_group_name"])
        _emit(stack, "RestApiUrlStaging", staging["rest_url"])
        _emit(stack, "WebSocketUrlStaging", staging["ws_url"])
        _emit(stack, "WebSocketConnectionsUrlStaging", staging["ws_connections"])


def export_stack_b_compute_outputs(stack: Stack, compute: IConstruct) -> None:
    exports: dict[str, Any] = getattr(compute, "stable_outputs", None) or {}
    for key, value in exports.items():
        if value is not None and str(value) != "":
            _emit(stack, key, str(value))


def export_stack_b_extension_outputs(stack: Stack, extension: IConstruct) -> None:
    for key, value in (getattr(extension, "runtime_outputs", None) or {}).items():
        if value is not None and str(value) != "":
            _emit(stack, key, str(value))
    for key, value in (getattr(extension, "inventory_outputs", None) or {}).items():
        if value is not None and str(value) != "":
            _emit(stack, key, str(value))
