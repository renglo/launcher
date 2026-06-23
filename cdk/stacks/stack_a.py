"""Stack A (pre-seed): Cognito, storage, backend runtime (ECR, IAM, CodeDeploy, OIDC)."""

from __future__ import annotations

from aws_cdk import Stack
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
