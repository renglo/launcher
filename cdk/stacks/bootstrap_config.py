"""SSM bootstrap config parameters — written automatically on stack-b deploy."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from aws_cdk import Fn, Token
from aws_cdk import aws_ssm as ssm
from constructs import Construct

_CDK_DIR = Path(__file__).resolve().parents[1]
if str(_CDK_DIR) not in sys.path:
    sys.path.insert(0, str(_CDK_DIR))

from lib.config_builder import (  # noqa: E402
    build_deploy_input_envelope,
    build_deploy_input_vars,
    build_ecs_network_vars,
    build_launcher_vars,
    build_platform_vars_envelope,
    ssm_deploy_input_path,
    ssm_ecs_security_groups_path,
    ssm_ecs_subnets_path,
    ssm_ecs_vpc_path,
    ssm_platform_vars_path,
)


class BootstrapConfigStack(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        aws_account: str,
        aws_region: str,
        github_repo: str,
        github_handlers_repo: str,
        enable_staging: bool,
        compute_type: str,
        network_mode: str | None,
        auth: Any,
        storage: Any,
        console: Any,
        runtime: Any,
        app: Any,
        compute: Any,
        extension: Any | None = None,
        from_email: str = "",
    ) -> None:
        super().__init__(scope, construct_id)

        compute_outputs: dict[str, Any] = dict(getattr(compute, "stable_outputs", None) or {})
        extension_vars: dict[str, Any] = {}
        if extension is not None:
            extension_vars = dict(getattr(extension, "runtime_outputs", None) or {})

        ecs_network = build_ecs_network_vars(
            compute_type=compute_type,
            network_mode_cfg=network_mode,
        )

        shared_launcher = {
            "env_name": env_name,
            "aws_region": aws_region,
            "aws_account": aws_account,
            "data_bucket": storage.data_bucket.bucket_name,
            "cognito_user_pool_id": auth.user_pool_id,
            "cognito_app_client_id": auth.app_client_id,
            "cognito_domain": auth.cognito_domain,
            "tenant_role_arn": runtime.tt_role.role_arn,
            "backend_ecr_repo_name": runtime.backend_repo.repository_name,
            "codedeploy_app_name": runtime.cd_app.application_name,
            "amplify_app_id": console.amplify_app_id,
            "amplify_default_domain": console.default_domain,
            "compute_outputs": compute_outputs,
            "ecs_network": ecs_network,
            "extension_vars": extension_vars,
            "from_email": (from_email or "").strip(),
        }

        prod_vars = build_launcher_vars(
            stage="production",
            stage_app=app.production,
            amplify_console_url=console.production_url,
            **shared_launcher,
        )
        prod_envelope = build_platform_vars_envelope(
            github_repo=github_repo,
            stage="production",
            vars_dict=prod_vars,
        )
        self._ssm_json_param(
            "PlatformVarsProduction",
            ssm_platform_vars_path(env_name, "production"),
            prod_envelope,
        )

        if enable_staging and app.staging is not None:
            staging_vars = build_launcher_vars(
                stage="staging",
                stage_app=app.staging,
                amplify_console_url=console.staging_url or "",
                **shared_launcher,
            )
            staging_envelope = build_platform_vars_envelope(
                github_repo=github_repo,
                stage="staging",
                vars_dict=staging_vars,
            )
            self._ssm_json_param(
                "PlatformVarsStaging",
                ssm_platform_vars_path(env_name, "staging"),
                staging_envelope,
            )

        deploy_vars = build_deploy_input_vars(
            env_name=env_name,
            aws_region=aws_region,
            aws_account=aws_account,
            data_bucket=storage.data_bucket.bucket_name,
            cognito_user_pool_id=auth.user_pool_id,
            cognito_app_client_id=auth.app_client_id,
            tenant_role_arn=runtime.tt_role.role_arn,
            production_app=app.production,
            compute_outputs=compute_outputs,
            ecs_network=ecs_network,
            extension_vars=extension_vars,
        )
        handlers_ecr_uri = compute_outputs.get("HandlersEcrRepoUri", "")
        if handlers_ecr_uri:
            deploy_vars["ECR_IMAGE_URI"] = Fn.join("", [handlers_ecr_uri, ":latest"])
        deploy_envelope = build_deploy_input_envelope(
            github_handlers_repo=github_handlers_repo,
            vars_dict=deploy_vars,
        )
        self._ssm_json_param(
            "DeployInput",
            ssm_deploy_input_path(env_name),
            deploy_envelope,
        )

        if compute_type == "ec2":
            self._provision_ecs_network_ssm(env_name, compute_outputs)

    def _provision_ecs_network_ssm(self, env_name: str, compute_outputs: dict[str, Any]) -> None:
        """Write ECS VPC/subnet/SG IDs as separate SSM params (Fn::If tokens cannot use to_json_string)."""
        vpc = compute_outputs.get("HandlersComputeVpcId")
        subnets = compute_outputs.get("HandlersComputeSubnetIds")
        security_groups = compute_outputs.get("HandlersComputeSecurityGroupId")
        if vpc is None or subnets is None or security_groups is None:
            return
        self._ssm_string_param("EcsVpc", ssm_ecs_vpc_path(env_name), vpc)
        self._ssm_string_param("EcsSubnets", ssm_ecs_subnets_path(env_name), subnets)
        self._ssm_string_param(
            "EcsSecurityGroups",
            ssm_ecs_security_groups_path(env_name),
            security_groups,
        )

    def _ssm_json_param(self, construct_id: str, name: str, payload: dict[str, Any]) -> ssm.CfnParameter:
        return ssm.CfnParameter(
            self,
            construct_id,
            name=name,
            type="String",
            tier="Standard",
            value=Fn.to_json_string(payload),
        )

    def _ssm_string_param(self, construct_id: str, name: str, value: Any) -> ssm.CfnParameter:
        return ssm.CfnParameter(
            self,
            construct_id,
            name=name,
            type="String",
            tier="Standard",
            value=Token.as_string(value),
        )
