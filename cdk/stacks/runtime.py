"""Runtime resources: Backend infrastructure — ECR, IAM, CodeDeploy, OIDC.

Part of stack-a. Lambda functions and API Gateway are in stack-b after the seed
image has been pushed to ECR.
"""

from __future__ import annotations

from aws_cdk import CfnCondition, CfnOutput, RemovalPolicy
from aws_cdk import aws_codedeploy as codedeploy
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_iam as iam
from constructs import Construct

from platform_defaults import backend_ecr_repository_name

# Account-level GitHub Actions OIDC provider host (one IAM OIDC provider per account/URL).
GITHUB_OIDC_PROVIDER_ARN_SUFFIX = "token.actions.githubusercontent.com"
GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_THUMBPRINT = "6938fd4d98bab03faadb97b34396831e3780aea1"
GITHUB_OIDC_CLIENT_ID = "sts.amazonaws.com"
DESCRIPTION = "Reglo Deployment"


def _tt_policy_document(
    env_name: str,
    region: str,
    account: str,
    cognito_user_pool_id: str,
    s3_bucket_name: str,
) -> iam.PolicyDocument:
    handlers_bucket = f"{env_name}-handlers-ecs-{account}"
    backend_repo_name = backend_ecr_repository_name(env_name)
    return iam.PolicyDocument(
        statements=[
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[
                    f"arn:aws:lambda:{region}:{account}:function:{env_name}*",
                    f"arn:aws:lambda:{region}:{account}:function:{env_name}*:*",
                ],
            ),
            iam.PolicyStatement(
                actions=["apigateway:POST", "apigateway:GET", "apigateway:PUT", "apigateway:DELETE"],
                resources=[
                    f"arn:aws:apigateway:{region}::/restapis/*",
                    f"arn:aws:apigateway:{region}::/apis/*",
                ],
            ),
            iam.PolicyStatement(
                sid="S3ListEnvBucket",
                actions=["s3:ListBucket"],
                resources=[
                    f"arn:aws:s3:::{s3_bucket_name}",
                    f"arn:aws:s3:::{env_name}-*",
                ],
            ),
            iam.PolicyStatement(
                sid="S3ObjectsEnvBucket",
                actions=["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
                resources=[
                    f"arn:aws:s3:::{s3_bucket_name}/*",
                    f"arn:aws:s3:::{env_name}-*/*",
                ],
            ),
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                    "logs:GetLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/{env_name}*",
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/{env_name}*:log-stream:*",
                ],
            ),
            iam.PolicyStatement(
                sid="EcrPullBackendImage",
                actions=[
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchCheckLayerAvailability",
                ],
                resources=[f"arn:aws:ecr:{region}:{account}:repository/{backend_repo_name}"],
            ),
            iam.PolicyStatement(
                sid="EcrAuthToken",
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],
            ),
            iam.PolicyStatement(
                actions=[
                    "dynamodb:CreateTable",
                    "dynamodb:DescribeTable",
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                ],
                resources=[
                    f"arn:aws:dynamodb:{region}:{account}:table/{env_name}_*",
                    f"arn:aws:dynamodb:{region}:{account}:table/{env_name}_*/index/*",
                ],
            ),
            iam.PolicyStatement(actions=["ses:SendEmail"], resources=["*"]),
            iam.PolicyStatement(
                actions=[
                    "cognito-idp:ListUsers",
                    "cognito-idp:AdminCreateUser",
                    "cognito-idp:AdminSetUserPassword",
                    "cognito-idp:AdminInitiateAuth",
                    "cognito-idp:RespondToAuthChallenge",
                ],
                resources=[f"arn:aws:cognito-idp:{region}:{account}:userpool/{cognito_user_pool_id}"],
            ),
            iam.PolicyStatement(
                actions=[
                    "events:PutRule",
                    "events:PutTargets",
                    "events:RemoveTargets",
                    "events:DeleteRule",
                    "events:ListRules",
                    "events:DescribeRule",
                    "events:ListTargetsByRule",
                ],
                resources=[f"arn:aws:events:{region}:{account}:rule/{env_name}*"],
            ),
            iam.PolicyStatement(
                actions=["events:PutEvents"],
                resources=[f"arn:aws:events:{region}:{account}:event-bus/default"],
            ),
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[f"arn:aws:iam::{account}:role/{env_name}_tt_role"],
                conditions={"StringEquals": {"iam:PassedToService": "events.amazonaws.com"}},
            ),
            iam.PolicyStatement(
                actions=["execute-api:Invoke", "execute-api:ManageConnections"],
                resources=[
                    f"arn:aws:execute-api:{region}:{account}:*/*/POST/@connections/*",
                    f"arn:aws:execute-api:{region}:{account}:*/stage/POST/_schd/ping",
                ],
            ),
            iam.PolicyStatement(actions=["aoss:APIAccessAll"], resources=["*"]),
            # ECS handlers handshake (mirrors create_iam_policy._ecs_handlers_handshake_statements)
            iam.PolicyStatement(
                sid="ECSRunTask",
                actions=["ecs:RunTask", "ecs:DescribeTasks", "ecs:ListTasks", "ecs:DescribeClusters"],
                resources=[
                    f"arn:aws:ecs:{region}:{account}:cluster/{env_name}-handlers",
                    f"arn:aws:ecs:{region}:{account}:task-definition/{env_name}-handlers-ecs:*",
                    f"arn:aws:ecs:{region}:{account}:task/{env_name}-handlers/*",
                ],
            ),
            iam.PolicyStatement(
                sid="ECSPassRole",
                actions=["iam:PassRole"],
                resources=[
                    f"arn:aws:iam::{account}:role/{env_name}-handlers-ecs-execution",
                    f"arn:aws:iam::{account}:role/{env_name}-handlers-ecs-task",
                ],
                conditions={"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
            ),
            iam.PolicyStatement(
                sid="ECSHandshakeS3",
                actions=["s3:PutObject", "s3:GetObject"],
                resources=[f"arn:aws:s3:::{handlers_bucket}/*"],
            ),
        ]
    )


def _backend_lambda_function_name(env_name: str, stage: str) -> str:
    return f"{env_name}-backend-{stage}"


def _deploy_permissions_policy(
    env_name: str,
    region: str,
    account: str,
    s3_bucket_name: str,
    *,
    enable_staging: bool,
    amplify_app_id: str | None = None,
) -> iam.PolicyDocument:
    """Permissions for the releases-repo GitHub Actions OIDC deploy role."""
    ecr_repo_arn = f"arn:aws:ecr:{region}:{account}:repository/{backend_ecr_repository_name(env_name)}"
    codedeploy_app_arn = f"arn:aws:codedeploy:{region}:{account}:application:{env_name}-backend-codedeploy"
    codedeploy_group_arn = f"arn:aws:codedeploy:{region}:{account}:deploymentgroup:{env_name}-backend-codedeploy/*"
    codedeploy_config_arn = f"arn:aws:codedeploy:{region}:{account}:deploymentconfig:*"
    lambda_execution_role_arn = f"arn:aws:iam::{account}:role/{env_name}_tt_role"

    backend_lambda_arns = [
        f"arn:aws:lambda:{region}:{account}:function:{_backend_lambda_function_name(env_name, 'production')}",
        f"arn:aws:lambda:{region}:{account}:function:{_backend_lambda_function_name(env_name, 'production')}:*",
    ]
    if enable_staging:
        backend_lambda_arns.extend(
            [
                f"arn:aws:lambda:{region}:{account}:function:{_backend_lambda_function_name(env_name, 'staging')}",
                f"arn:aws:lambda:{region}:{account}:function:{_backend_lambda_function_name(env_name, 'staging')}:*",
            ]
        )

    statements: list[iam.PolicyStatement] = [
        iam.PolicyStatement(
            sid="ReadIdentity",
            actions=["sts:GetCallerIdentity"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="EcrPushPull",
            actions=[
                "ecr:BatchGetImage",
                "ecr:BatchCheckLayerAvailability",
                "ecr:InitiateLayerUpload",
                "ecr:UploadLayerPart",
                "ecr:CompleteLayerUpload",
                "ecr:PutImage",
            ],
            resources=[ecr_repo_arn],
        ),
        iam.PolicyStatement(
            sid="EcrAuthToken",
            actions=["ecr:GetAuthorizationToken"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="BackendLambdaDeploy",
            actions=[
                "lambda:CreateFunction",
                "lambda:GetFunction",
                "lambda:GetFunctionConfiguration",
                "lambda:UpdateFunctionCode",
                "lambda:UpdateFunctionConfiguration",
                "lambda:PublishVersion",
                "lambda:CreateAlias",
                "lambda:UpdateAlias",
                "lambda:GetAlias",
                "lambda:AddPermission",
            ],
            resources=backend_lambda_arns,
        ),
        iam.PolicyStatement(
            sid="CodeDeployLambdaRelease",
            actions=[
                "codedeploy:CreateDeployment",
                "codedeploy:RegisterApplicationRevision",
                "codedeploy:GetDeployment",
                "codedeploy:GetDeploymentConfig",
                "codedeploy:GetDeploymentGroup",
                "codedeploy:GetApplication",
            ],
            resources=[codedeploy_app_arn, codedeploy_group_arn, codedeploy_config_arn],
        ),
        iam.PolicyStatement(
            sid="PassExecutionRole",
            actions=["iam:PassRole"],
            resources=[lambda_execution_role_arn],
            conditions={"StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}},
        ),
        iam.PolicyStatement(
            sid="CloudFormationDescribe",
            actions=["cloudformation:DescribeStacks"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="S3WriteState",
            actions=["s3:PutObject", "s3:GetObject"],
            resources=[f"arn:aws:s3:::{s3_bucket_name}/params/*"],
        ),
    ]
    if amplify_app_id:
        statements.append(
            iam.PolicyStatement(
                sid="AmplifyConsoleDeploy",
                actions=[
                    "amplify:CreateDeployment",
                    "amplify:StartDeployment",
                    "amplify:GetJob",
                    "amplify:StopJob",
                    "amplify:GetApp",
                    "amplify:GetBranch",
                ],
                resources=[f"arn:aws:amplify:{region}:{account}:apps/{amplify_app_id}/*"],
            )
        )

    return iam.PolicyDocument(statements=statements)


class RuntimeStack(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        aws_account: str,
        aws_region: str,
        github_repo: str,
        cognito_user_pool_id: str,
        s3_bucket_name: str,
        enable_staging: bool = True,
        amplify_app_id: str | None = None,
        create_github_oidc_condition: CfnCondition | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        backend_repo_name = backend_ecr_repository_name(env_name)
        backend_repo = ecr.Repository(
            self,
            "BackendEcrRepo",
            repository_name=backend_repo_name,
            removal_policy=RemovalPolicy.DESTROY,
        )
        backend_repo.add_lifecycle_rule(max_image_count=10)

        # --- Tenant IAM policy + role ---
        tt_policy = iam.ManagedPolicy(
            self,
            "TenantPolicy",
            managed_policy_name=f"{env_name}_tt_policy",
            document=_tt_policy_document(
                env_name, aws_region, aws_account, cognito_user_pool_id, s3_bucket_name
            ),
        )
        tt_role = iam.Role(
            self,
            "TenantRole",
            role_name=f"{env_name}_tt_role",
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal("lambda.amazonaws.com"),
                iam.ServicePrincipal("events.amazonaws.com"),
                iam.ServicePrincipal("apigateway.amazonaws.com"),
            ),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                tt_policy,
            ],
            description=DESCRIPTION,
        )

        self.tt_policy = tt_policy
        self.tt_role = tt_role

        # --- ECR policy (allow Lambda to pull from the private repo after step 4) ---
        backend_repo.add_to_resource_policy(
            iam.PolicyStatement(
                sid="LambdaECRPull",
                principals=[iam.ServicePrincipal("lambda.amazonaws.com")],
                actions=[
                    "ecr:BatchGetImage",
                    "ecr:DeleteRepositoryPolicy",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:GetRepositoryPolicy",
                    "ecr:SetRepositoryPolicy",
                ],
                conditions={
                    "StringLike": {
                        "aws:sourceArn": f"arn:aws:lambda:{aws_region}:{aws_account}:function:*"
                    }
                },
            )
        )

        # --- CodeDeploy ---
        cd_service_role = iam.Role(
            self,
            "CodeDeployServiceRole",
            role_name=f"{env_name}-codedeploy-lambda-role",
            assumed_by=iam.ServicePrincipal("codedeploy.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSCodeDeployRoleForLambda"
                )
            ],
            description=DESCRIPTION,
        )
        cd_app = codedeploy.CfnApplication(
            self,
            "CodeDeployApp",
            application_name=f"{env_name}-backend-codedeploy",
            compute_platform="Lambda",
        )
        codedeploy.CfnDeploymentGroup(
            self,
            "CodeDeployGroupProduction",
            application_name=cd_app.application_name,
            deployment_group_name=f"{env_name}-backend-production",
            service_role_arn=cd_service_role.role_arn,
            deployment_config_name="CodeDeployDefault.LambdaCanary10Percent10Minutes",
            deployment_style=codedeploy.CfnDeploymentGroup.DeploymentStyleProperty(
                deployment_type="BLUE_GREEN",
                deployment_option="WITH_TRAFFIC_CONTROL",
            ),
        )
        if enable_staging:
            codedeploy.CfnDeploymentGroup(
                self,
                "CodeDeployGroupStaging",
                application_name=cd_app.application_name,
                deployment_group_name=f"{env_name}-backend-staging",
                service_role_arn=cd_service_role.role_arn,
                deployment_config_name="CodeDeployDefault.LambdaAllAtOnce",
                deployment_style=codedeploy.CfnDeploymentGroup.DeploymentStyleProperty(
                    deployment_type="BLUE_GREEN",
                    deployment_option="WITH_TRAFFIC_CONTROL",
                ),
            )

        # --- GitHub OIDC + deploy roles ---
        oidc_provider_arn = (
            f"arn:aws:iam::{aws_account}:oidc-provider/{GITHUB_OIDC_PROVIDER_ARN_SUFFIX}"
        )
        if create_github_oidc_condition is not None:
            oidc_provider_resource = iam.CfnOIDCProvider(
                self,
                "GitHubOidcProviderResource",
                url=GITHUB_OIDC_URL,
                client_id_list=[GITHUB_OIDC_CLIENT_ID],
                thumbprint_list=[GITHUB_OIDC_THUMBPRINT],
            )
            oidc_provider_resource.cfn_options.condition = create_github_oidc_condition
        oidc_provider = iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
            self,
            "GitHubOidcProvider",
            open_id_connect_provider_arn=oidc_provider_arn,
        )
        deploy_policy_doc = _deploy_permissions_policy(
            env_name,
            aws_region,
            aws_account,
            s3_bucket_name,
            enable_staging=enable_staging,
            amplify_app_id=amplify_app_id,
        )

        def _oidc_role(stage: str) -> iam.Role:
            return iam.Role(
                self,
                f"OidcDeployRole{stage.capitalize()}",
                role_name=f"GitHubActionsDeployRole-{env_name}-{stage}",
                assumed_by=iam.WebIdentityPrincipal(
                    oidc_provider.open_id_connect_provider_arn,
                    conditions={
                        "StringEquals": {
                            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                        },
                        "StringLike": {
                            "token.actions.githubusercontent.com:sub": f"repo:{github_repo}:environment:{stage}"
                        },
                    },
                ),
                inline_policies={
                    f"GitHubActionsDeployPolicy-{env_name}-{stage}": deploy_policy_doc
                },
                description=DESCRIPTION,
            )

        prod_oidc_role = _oidc_role("production")
        staging_oidc_role = _oidc_role("staging") if enable_staging else None

        self.backend_repo = backend_repo
        self.cd_app = cd_app
        self.oidc_provider = oidc_provider
        self.oidc_deploy_role_production = prod_oidc_role
        self.oidc_deploy_role_staging = staging_oidc_role

        # --- Outputs ---
        CfnOutput(self, "BackendEcrRepoName", value=backend_repo.repository_name)
        CfnOutput(self, "BackendEcrRepoUri", value=backend_repo.repository_uri)
        CfnOutput(self, "TenantPolicyArn", value=tt_policy.managed_policy_arn)
        CfnOutput(self, "TenantRoleArn", value=tt_role.role_arn)
        CfnOutput(self, "CodeDeployAppName", value=cd_app.application_name)
        CfnOutput(self, "OidcProviderArn", value=oidc_provider.open_id_connect_provider_arn)
        CfnOutput(self, "OidcDeployRoleArnProduction", value=prod_oidc_role.role_arn)
        if staging_oidc_role:
            CfnOutput(self, "OidcDeployRoleArnStaging", value=staging_oidc_role.role_arn)
