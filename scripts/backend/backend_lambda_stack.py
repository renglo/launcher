from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_apigateway as apigateway,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_lambda as lambda_,
)
from constructs import Construct


class BackendLambdaStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        stage_name: str,
        image_tag: str,
        runtime_env: dict[str, str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        repository_name = self.node.try_get_context("ecr_repo_name") or f"{env_name}_backend"
        architecture = self.node.try_get_context("architecture") or "x86_64"
        websocket_url = self.node.try_get_context("websocket_url") or ""
        websocket_connections = self.node.try_get_context("websocket_connections") or ""

        lambda_env = dict(runtime_env or {})
        lambda_env["SYS_ENV"] = stage_name
        lambda_env["WEBSOCKET_URL"] = websocket_url
        lambda_env["VITE_WEBSOCKET_URL"] = websocket_url
        lambda_env["WEBSOCKET_CONNECTIONS"] = websocket_connections

        configured_role_arn = lambda_env.get("ROLE_ARN", "").strip()
        if configured_role_arn:
            role = iam.Role.from_role_arn(
                self,
                f"BackendLambdaImportedRole{stage_name}",
                role_arn=configured_role_arn,
                mutable=False,
            )
        else:
            role = iam.Role(
                self,
                f"BackendLambdaRole{stage_name}",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name(
                        "service-role/AWSLambdaBasicExecutionRole"
                    )
                ],
            )

        repository = ecr.Repository.from_repository_name(
            self, f"BackendEcrRepo{stage_name}", repository_name=repository_name
        )

        backend_fn = lambda_.DockerImageFunction(
            self,
            f"BackendLambda{stage_name}",
            function_name=f"{env_name}-backend-{stage_name}",
            code=lambda_.DockerImageCode.from_ecr(
                repository, tag_or_digest=image_tag
            ),
            memory_size=1024 if stage_name == "production" else 512,
            timeout=Duration.seconds(30),
            role=role,
            architecture=(
                lambda_.Architecture.X86_64
                if architecture == "x86_64"
                else lambda_.Architecture.ARM_64
            ),
            environment=lambda_env,
            description="Reglo Deployment",
        )

        version = backend_fn.current_version
        alias_name = stage_name
        alias = lambda_.Alias(
            self,
            f"BackendAlias{stage_name}",
            alias_name=alias_name,
            version=version,
        )

        rest_api = apigateway.LambdaRestApi(
            self,
            f"BackendRestApi{stage_name}",
            rest_api_name=f"{env_name}-api-{stage_name}",
            handler=alias,
            proxy=True,
            deploy_options=apigateway.StageOptions(stage_name=stage_name, description="Reglo Deployment"),
        )

        CfnOutput(self, f"BackendFunctionName{stage_name}", value=backend_fn.function_name)
        CfnOutput(self, f"BackendVersionArn{stage_name}", value=version.function_arn)
        CfnOutput(self, f"BackendAliasArn{stage_name}", value=alias.function_arn)
        CfnOutput(self, f"BackendRestApiUrl{stage_name}", value=rest_api.url)
