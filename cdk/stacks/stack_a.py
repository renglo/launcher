"""Stack A (pre-seed): Cognito, storage, backend runtime (ECR, IAM, CodeDeploy, OIDC)."""

from __future__ import annotations

from aws_cdk import CfnCondition, CfnParameter, Fn, Stack
from constructs import Construct

from stack_names import stack_a_description
from stacks.auth import AuthStack
from stacks.runtime import RuntimeStack
from stacks.stack_exports import export_stack_a_outputs
from stacks.storage import StorageStack


class StackA(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        aws_account: str,
        aws_region: str,
        github_repo: str,
        enable_staging: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(
            scope,
            construct_id,
            description=stack_a_description(),
            **kwargs,
        )
        create_oidc = CfnParameter(
            self,
            "CreateGitHubOIDC",
            type="String",
            default="false",
            allowed_values=["true", "false"],
            description=(
                "Create the GitHub Actions OIDC provider in this account. "
                "Set to true only if token.actions.githubusercontent.com is not already registered."
            ),
        )
        create_oidc_condition = CfnCondition(
            self,
            "CreateGitHubOIDCCondition",
            expression=Fn.condition_equals(create_oidc.value_as_string, "true"),
        )
        auth = AuthStack(self, "Auth", env_name=env_name)
        storage = StorageStack(
            self,
            "Storage",
            env_name=env_name,
            aws_account=aws_account,
            aws_region=aws_region,
        )
        runtime = RuntimeStack(
            self,
            "Runtime",
            env_name=env_name,
            aws_account=aws_account,
            aws_region=aws_region,
            github_repo=github_repo,
            cognito_user_pool_id=auth.user_pool_id,
            s3_bucket_name=storage.bucket_name,
            enable_staging=enable_staging,
            create_github_oidc_condition=create_oidc_condition,
        )

        self.auth = auth
        self.storage = storage
        self.runtime = runtime
        self.tt_policy = runtime.tt_policy
        self.tt_role = runtime.tt_role

        export_stack_a_outputs(
            self,
            auth=auth,
            storage=storage,
            runtime=runtime,
            env_name=env_name,
            enable_staging=enable_staging,
        )
