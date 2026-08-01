"""Stack A (pre-seed): Cognito, storage, backend runtime (ECR, seed CodeBuild, IAM, CodeDeploy, OIDC)."""

from __future__ import annotations

from aws_cdk import CfnCondition, CfnParameter, Fn, Stack
from constructs import Construct

from stack_names import stack_a_description
from stacks.auth import AuthStack
from stacks.console import ConsoleStack
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
        # Env-agnostic: unresolved tokens → AWS::AccountId / AWS::Region at deploy.
        aws_account = self.account
        aws_region = self.region
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
        storage = StorageStack(
            self,
            "Storage",
            env_name=env_name,
            aws_account=aws_account,
            aws_region=aws_region,
        )
        console = ConsoleStack(
            self,
            "Console",
            env_name=env_name,
            enable_staging=enable_staging,
        )
        callback_urls = [console.production_url, console.production_callback_url]
        logout_urls = [console.production_url]
        if enable_staging and console.staging_url and console.staging_callback_url:
            callback_urls.extend([console.staging_url, console.staging_callback_url])
            logout_urls.append(console.staging_url)
        auth = AuthStack(
            self,
            "Auth",
            env_name=env_name,
            aws_region=aws_region,
            console_callback_urls=callback_urls,
            console_logout_urls=logout_urls,
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
            amplify_app_id=console.amplify_app_id,
            create_github_oidc_condition=create_oidc_condition,
        )

        self.auth = auth
        self.storage = storage
        self.console = console
        self.runtime = runtime
        self.tt_policy = runtime.tt_policy
        self.tt_role = runtime.tt_role

        export_stack_a_outputs(
            self,
            auth=auth,
            storage=storage,
            console=console,
            runtime=runtime,
            env_name=env_name,
            enable_staging=enable_staging,
        )
