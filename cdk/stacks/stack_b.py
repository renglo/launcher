"""Stack B (post-seed): backend app, handlers compute, extension resources."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from aws_cdk import CfnCondition, CfnParameter, Fn, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

from stack_names import stack_b_description
from stacks.app import AppStack
from stacks.blueprint_uploader import BlueprintUploader
from stacks.bootstrap_config import BootstrapConfigStack
from stacks.extension import ExtensionStack
from stacks.stack_exports import (
    export_stack_b_app_outputs,
    export_stack_b_compute_outputs,
    export_stack_b_extension_outputs,
)
_ROOT = Path(__file__).resolve().parents[1]
_EXTENSIONS_DIR = _ROOT / "extensions"
if (_EXTENSIONS_DIR / "compute_stack.py").is_file():
    sys.path.insert(0, str(_EXTENSIONS_DIR))
else:
    sys.path.insert(0, str(_ROOT.parents[1] / "extensions-service" / "scripts"))

from compute_stack import ComputeStack, HANDLERS_NETWORK_MODE_CREATE, HANDLERS_NETWORK_MODE_EXISTING  # noqa: E402


class StackB(Stack):
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
        enable_staging: bool = True,
        architecture: str = "x86_64",
        compute_type: str = "fargate",
        network_mode: str | None = None,
        ec2_instance_type: str = "t3.medium",
        ec2_min_instances: int = 0,
        ec2_desired_instances: int = 1,
        ec2_max_instances: int = 2,
        tenant_policy: iam.IManagedPolicy | None = None,
        tenant_role: iam.IRole | None = None,
        stack_a_auth: Any = None,
        stack_a_storage: Any = None,
        stack_a_console: Any = None,
        stack_a_runtime: Any = None,
        extension_folder: Path | None = None,
        extension_manifest: dict[str, Any] | None = None,
        extension_config: dict[str, Any] | None = None,
        include_extension: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(
            scope,
            construct_id,
            description=stack_b_description(include_extension=include_extension),
            **kwargs,
        )
        app = AppStack(
            self,
            "App",
            env_name=env_name,
            aws_account=aws_account,
            aws_region=aws_region,
            enable_staging=enable_staging,
            architecture=architecture,
        )
        handlers_network_params = None
        if compute_type == "ec2":
            handlers_network_mode = CfnParameter(
                self,
                "HandlersNetworkMode",
                type="String",
                default=HANDLERS_NETWORK_MODE_CREATE,
                allowed_values=[HANDLERS_NETWORK_MODE_CREATE, HANDLERS_NETWORK_MODE_EXISTING],
                description=(
                    "Handlers EC2 network layout. create provisions a dedicated VPC and subnets; "
                    "existing uses ExistingVpcId and ExistingSubnetIds."
                ),
            )
            handlers_network_params = {
                "handlers_network_mode": handlers_network_mode,
                "create_dedicated_network": CfnCondition(
                    self,
                    "CreateHandlersDedicatedNetwork",
                    expression=Fn.condition_equals(
                        handlers_network_mode.value_as_string,
                        HANDLERS_NETWORK_MODE_CREATE,
                    ),
                ),
                "use_existing_network": CfnCondition(
                    self,
                    "UseHandlersExistingNetwork",
                    expression=Fn.condition_equals(
                        handlers_network_mode.value_as_string,
                        HANDLERS_NETWORK_MODE_EXISTING,
                    ),
                ),
                "existing_vpc_id": CfnParameter(
                    self,
                    "ExistingVpcId",
                    type="String",
                    default="",
                    description=(
                        "VPC ID for handlers EC2 capacity when HandlersNetworkMode is existing. "
                        "Ignored when HandlersNetworkMode is create."
                    ),
                ),
                "existing_subnet_ids": CfnParameter(
                    self,
                    "ExistingSubnetIds",
                    type="CommaDelimitedList",
                    default="",
                    description=(
                        "Subnet IDs for the handlers Auto Scaling group when HandlersNetworkMode is existing. "
                        "All subnets must belong to ExistingVpcId. Use subnets in at least two "
                        "Availability Zones for high availability. Ignored when HandlersNetworkMode is create."
                    ),
                ),
            }

        compute = ComputeStack(
            self,
            "Compute",
            env_name=env_name,
            aws_account=aws_account,
            aws_region=aws_region,
            compute_type=compute_type,
            ec2_instance_type=ec2_instance_type,
            ec2_min_instances=ec2_min_instances,
            ec2_desired_instances=ec2_desired_instances,
            ec2_max_instances=ec2_max_instances,
            github_handlers_repo=github_handlers_repo,
            enable_staging=enable_staging,
            tenant_policy=tenant_policy,
            handlers_network_params=handlers_network_params,
        )

        self.app = app
        self.compute = compute
        extension = None

        if extension_folder is not None and extension_manifest is not None:
            attach_roles: dict[str, iam.IRole] = {}
            if tenant_role is not None:
                attach_roles[f"{env_name}_tt_role"] = tenant_role
            handlers_lambda_role = getattr(compute, "handlers_lambda_role", None)
            if handlers_lambda_role is not None:
                attach_roles[f"{env_name}-handlers-role"] = handlers_lambda_role
            handlers_ecs_task_role = getattr(compute, "handlers_ecs_task_role", None)
            if handlers_ecs_task_role is not None:
                attach_roles[f"{env_name}-handlers-ecs-task"] = handlers_ecs_task_role

            extension = ExtensionStack(
                self,
                "Extension",
                env_name=env_name,
                aws_account=aws_account,
                extension_folder=extension_folder,
                manifest=extension_manifest,
                extension_config=extension_config or {},
                compute_type=compute_type,
                attach_roles=attach_roles,
            )
            self.extension = extension

        export_stack_b_app_outputs(self, app)
        export_stack_b_compute_outputs(self, compute)
        if extension is not None:
            export_stack_b_extension_outputs(self, extension)

        if (
            stack_a_auth is not None
            and stack_a_storage is not None
            and stack_a_console is not None
            and stack_a_runtime is not None
        ):
            BootstrapConfigStack(
                self,
                "BootstrapConfig",
                env_name=env_name,
                aws_account=aws_account,
                aws_region=aws_region,
                github_repo=github_repo,
                github_handlers_repo=github_handlers_repo,
                enable_staging=enable_staging,
                compute_type=compute_type,
                network_mode=network_mode,
                auth=stack_a_auth,
                storage=stack_a_storage,
                console=stack_a_console,
                runtime=stack_a_runtime,
                app=app,
                compute=compute,
                extension=extension,
            )

        BlueprintUploader(self, "BlueprintUploader", env_name=env_name)
