"""ExtensionStack: extension-specific AWS resources delivered as CloudFormation.

Resources are declared in the extension repo under installer/infra/cdk_extension.json
(e.g. arbitiumlab). Replaces the post-deploy provision_extension.sh flow for CDK installs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aws_cdk import CfnDeletionPolicy, CfnOutput, RemovalPolicy, Tags
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct

_DESCRIPTION = "Reglo Deployment"


class ExtensionStack(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        aws_account: str,
        extension_folder: Path,
        manifest: dict[str, Any],
        extension_config: dict[str, Any],
        compute_type: str = "fargate",
        attach_roles: dict[str, iam.IRole] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        infra_dir = extension_folder / "installer" / "infra"
        policy_file = infra_dir / str(manifest["policy_file"])
        if not policy_file.is_file():
            raise FileNotFoundError(f"Extension policy document not found: {policy_file}")

        policy_name = str(manifest["policy_name"]).replace("{env}", env_name)
        policy_description = str(
            manifest.get("policy_description", "Extension actions policy")
        )
        policy_document = iam.PolicyDocument.from_json(
            json.loads(policy_file.read_text(encoding="utf-8"))
        )

        actions_policy = iam.ManagedPolicy(
            self,
            "ActionsPolicy",
            managed_policy_name=policy_name,
            document=policy_document,
            description=policy_description,
        )
        policy_cfn = actions_policy.node.default_child
        policy_cfn.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE
        policy_cfn.cfn_options.update_replace_policy = CfnDeletionPolicy.DELETE

        runtime_outputs: dict[str, str] = {}
        inventory_outputs = {
            "ActionsPolicyArn": actions_policy.managed_policy_arn,
            "ActionsPolicyName": policy_name,
        }

        for bucket_cfg in manifest.get("s3_buckets", []):
            bucket_id = str(bucket_cfg.get("id", "ExtensionBucket"))
            name_prefix = str(bucket_cfg["name_prefix"]).replace("{env}", env_name)
            bucket_name = f"{name_prefix}-{aws_account}"
            bucket = s3.Bucket(
                self,
                bucket_id,
                bucket_name=bucket_name,
                removal_policy=RemovalPolicy.DESTROY,
                auto_delete_objects=True,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                encryption=s3.BucketEncryption.S3_MANAGED,
            )
            Tags.of(bucket).add("Description", _DESCRIPTION)

            output_key = str(bucket_cfg.get("output_var", f"{bucket_id}BucketName"))
            CfnOutput(self, f"{bucket_id}BucketName", value=bucket.bucket_name)
            CfnOutput(self, output_key, value=bucket.bucket_name)
            runtime_outputs[output_key] = bucket.bucket_name

        role_refs = attach_roles or {}

        for role_template in manifest.get("attach_policy_to_roles", []):
            role_name = str(role_template).replace("{env}", env_name)
            if compute_type == "lambda_only" and role_name.endswith("-handlers-ecs-task"):
                continue
            role = role_refs.get(role_name)
            if role is None:
                raise ValueError(
                    f"Extension attach_policy_to_roles: no IAM role reference for {role_name!r}. "
                    "Pass attach_roles from stack-b with concrete Role constructs."
                )
            actions_policy.attach_to_role(role)

        CfnOutput(self, "ActionsPolicyArn", value=actions_policy.managed_policy_arn)
        CfnOutput(self, "ActionsPolicyName", value=policy_name)
        CfnOutput(self, "ExtensionPath", value=extension_folder.name)

        external_handlers = str(
            extension_config.get("EXTERNAL_HANDLERS") or env_name
        )
        external_handlers_ecs = str(
            extension_config.get("EXTERNAL_HANDLERS_ECS_HANDLERS") or ""
        )
        runtime_outputs["EXTERNAL_HANDLERS"] = external_handlers
        CfnOutput(self, "EXTERNAL_HANDLERS", value=external_handlers)
        if external_handlers_ecs:
            runtime_outputs["EXTERNAL_HANDLERS_ECS_HANDLERS"] = external_handlers_ecs
            CfnOutput(
                self,
                "EXTERNAL_HANDLERS_ECS_HANDLERS",
                value=external_handlers_ecs,
            )

        self.actions_policy = actions_policy
        self.runtime_outputs = runtime_outputs
        self.inventory_outputs = inventory_outputs
