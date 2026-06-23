"""Stack B (post-seed): backend app, handlers compute, extension resources."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from aws_cdk import Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

from stack_names import stack_b_description
from stacks.app import AppStack
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

from compute_stack import ComputeStack  # noqa: E402


class StackB(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        aws_account: str,
        aws_region: str,
        github_handlers_repo: str,
        enable_staging: bool = True,
        architecture: str = "x86_64",
        compute_type: str = "fargate",
        ec2_instance_type: str = "t3.medium",
        ec2_min_instances: int = 0,
        ec2_desired_instances: int = 1,
        ec2_max_instances: int = 2,
        tenant_policy: iam.IManagedPolicy | None = None,
        tenant_role: iam.IRole | None = None,
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
        )

        self.app = app
        self.compute = compute

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

            self.extension = ExtensionStack(
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

        export_stack_b_app_outputs(self, app)
        export_stack_b_compute_outputs(self, compute)
        if extension_folder is not None and extension_manifest is not None:
            export_stack_b_extension_outputs(self, self.extension)
