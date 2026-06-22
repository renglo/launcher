"""AppStack (Stack B): Backend Lambda functions + API Gateway.

Requires the seed image to already exist in ECR before deploying.

Deploy order:
  1. cdk deploy {env}-runtime                   (Stack A: ECR, IAM, CodeDeploy, OIDC)
  2. python scripts/upload_seed_image.py ...    (push seed image to ECR)
  3. cdk deploy {env}-app                       (Stack B: Lambda + API Gateway)

After Stack B, trigger the releases pipeline to update Lambda code to the
real application image and CodeDeploy will shift alias traffic.

NOTE: Re-deploying Stack B resets Lambda code to the seed image.
      Always re-run the releases pipeline after any Stack B change.
"""

from __future__ import annotations

from aws_cdk import CfnDeletionPolicy, CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_lambda as aws_lambda
from aws_cdk import aws_logs as logs
from constructs import Construct

DESCRIPTION = "Reglo Deployment"

_WS_REQUEST_TEMPLATE = """\
#set($action = $input.path('$.action'))
#set($data = $input.path('$.data'))
#set($entity_type = $input.path('$.entity_type'))
#set($entity_id = $input.path('$.entity_id'))
#set($thread = $input.path('$.thread'))
#set($portfolio = $input.path('$.portfolio'))
#set($org = $input.path('$.org'))
#set($core = $input.path('$.core'))
#set($next = $input.path('$.next'))
#set($auth = $input.path('$.auth'))
{
  "action": "$util.escapeJavaScript($action)",
  "data": $input.json('$.data'),
  "entity_type": "$util.escapeJavaScript($entity_type)",
  "entity_id": "$util.escapeJavaScript($entity_id)",
  "thread": "$util.escapeJavaScript($thread)",
  "portfolio": "$util.escapeJavaScript($portfolio)",
  "org": "$util.escapeJavaScript($org)",
  "core": "$util.escapeJavaScript($core)",
  "next": "$util.escapeJavaScript($util.defaultIfNullOrEmpty($next, ''))",
  "connectionId": "$context.connectionId",
  "auth": "$util.escapeJavaScript($auth)"
}"""


def _fn_name(env_name: str, stage: str) -> str:
    return f"{env_name}-backend-{stage}"


def _alias_arn(env_name: str, stage: str, region: str, account: str) -> str:
    return f"arn:aws:lambda:{region}:{account}:function:{_fn_name(env_name, stage)}:{stage}"


def _seed_image_uri(env_name: str, region: str, account: str) -> str:
    return f"{account}.dkr.ecr.{region}.amazonaws.com/{env_name}_backend:seed"


def _execution_role_arn(env_name: str, account: str) -> str:
    return f"arn:aws:iam::{account}:role/{env_name}_tt_role"


class AppStack(Stack):
    """Stack B — Lambda functions + API Gateway for all enabled stages."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        aws_account: str,
        aws_region: str,
        enable_staging: bool = True,
        architecture: str = "x86_64",
        timeout_seconds: int = 30,
        memory_mb: int = 512,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        seed_uri = _seed_image_uri(env_name, aws_region, aws_account)
        exec_role_arn = _execution_role_arn(env_name, aws_account)
        arch_cfn = "x86_64" if architecture == "x86_64" else "arm64"

        prod = self._make_stage(
            env_name=env_name,
            stage="production",
            aws_region=aws_region,
            aws_account=aws_account,
            seed_uri=seed_uri,
            exec_role_arn=exec_role_arn,
            arch_cfn=arch_cfn,
            timeout_seconds=timeout_seconds,
            memory_mb=memory_mb,
        )

        CfnOutput(self, "BackendLambdaFunctionNameProduction", value=prod["fn_name"])
        CfnOutput(self, "BackendLambdaAliasArnProduction", value=prod["alias_arn"])
        CfnOutput(self, "BackendLambdaLogGroupNameProduction", value=prod["log_group_name"])
        CfnOutput(self, "RestApiUrlProduction", value=prod["rest_url"])
        CfnOutput(self, "WebSocketUrlProduction", value=prod["ws_url"])
        CfnOutput(self, "WebSocketConnectionsUrlProduction", value=prod["ws_connections"])
        CfnOutput(self, "BackendLambdaArchitecture", value=architecture)
        CfnOutput(self, "BackendLambdaExecutionRoleArn", value=exec_role_arn)

        if enable_staging:
            staging = self._make_stage(
                env_name=env_name,
                stage="staging",
                aws_region=aws_region,
                aws_account=aws_account,
                seed_uri=seed_uri,
                exec_role_arn=exec_role_arn,
                arch_cfn=arch_cfn,
                timeout_seconds=timeout_seconds,
                memory_mb=memory_mb,
            )
            CfnOutput(self, "BackendLambdaFunctionNameStaging", value=staging["fn_name"])
            CfnOutput(self, "BackendLambdaAliasArnStaging", value=staging["alias_arn"])
            CfnOutput(self, "BackendLambdaLogGroupNameStaging", value=staging["log_group_name"])
            CfnOutput(self, "RestApiUrlStaging", value=staging["rest_url"])
            CfnOutput(self, "WebSocketUrlStaging", value=staging["ws_url"])
            CfnOutput(self, "WebSocketConnectionsUrlStaging", value=staging["ws_connections"])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_stage(
        self,
        *,
        env_name: str,
        stage: str,
        aws_region: str,
        aws_account: str,
        seed_uri: str,
        exec_role_arn: str,
        arch_cfn: str,
        timeout_seconds: int,
        memory_mb: int,
    ) -> dict:
        cap = stage.capitalize()
        fn_name = _fn_name(env_name, stage)
        the_alias_arn = _alias_arn(env_name, stage, aws_region, aws_account)

        # --- Lambda function (seed image; pipeline updates code later) ---
        fn = aws_lambda.CfnFunction(
            self,
            f"BackendLambda{cap}",
            function_name=fn_name,
            role=exec_role_arn,
            package_type="Image",
            code=aws_lambda.CfnFunction.CodeProperty(image_uri=seed_uri),
            architectures=[arch_cfn],
            timeout=timeout_seconds,
            memory_size=memory_mb,
            description=DESCRIPTION,
        )
        fn.cfn_options.deletion_policy = CfnDeletionPolicy.RETAIN
        fn.cfn_options.update_replace_policy = CfnDeletionPolicy.RETAIN

        # Publish initial version so alias can point to it
        version = aws_lambda.CfnVersion(
            self,
            f"BackendLambdaVersion{cap}",
            function_name=fn.ref,
            description=f"Seed version — {stage}",
        )
        version.add_dependency(fn)
        version.cfn_options.deletion_policy = CfnDeletionPolicy.RETAIN
        version.cfn_options.update_replace_policy = CfnDeletionPolicy.RETAIN

        alias = aws_lambda.CfnAlias(
            self,
            f"BackendLambdaAlias{cap}",
            function_name=fn.ref,
            function_version=version.attr_version,
            name=stage,
            description=f"{DESCRIPTION} {stage} traffic alias",
        )
        alias.add_dependency(version)
        alias.cfn_options.deletion_policy = CfnDeletionPolicy.RETAIN
        alias.cfn_options.update_replace_policy = CfnDeletionPolicy.RETAIN

        # --- CloudWatch log group ---
        log_group = logs.LogGroup(
            self,
            f"BackendLambdaLogGroup{cap}",
            log_group_name=f"/aws/lambda/{fn_name}",
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- REST API Gateway ---
        rest_api, rest_url = self._make_rest_api(
            env_name=env_name,
            stage=stage,
            aws_region=aws_region,
            aws_account=aws_account,
            alias_arn=the_alias_arn,
            fn_name=fn_name,
        )
        rest_api.add_dependency(alias)

        # --- WebSocket API Gateway ---
        chat_endpoint = f"{rest_url}_chat/message"
        ws_url, ws_connections = self._make_websocket_api(
            env_name=env_name,
            stage=stage,
            aws_region=aws_region,
            chat_endpoint=chat_endpoint,
        )

        return {
            "fn_name": fn_name,
            "alias_arn": the_alias_arn,
            "log_group_name": log_group.log_group_name,
            "rest_url": rest_url,
            "ws_url": ws_url,
            "ws_connections": ws_connections,
        }

    def _make_rest_api(
        self,
        *,
        env_name: str,
        stage: str,
        aws_region: str,
        aws_account: str,
        alias_arn: str,
        fn_name: str,
    ) -> tuple:
        cap = stage.capitalize()
        integration_uri = (
            f"arn:aws:apigateway:{aws_region}:lambda:path/2015-03-31/functions/"
            f"{alias_arn}/invocations"
        )

        rest_api = apigw.CfnRestApi(
            self,
            f"RestApi{cap}",
            name=f"{env_name}-api-{stage}",
            description=DESCRIPTION,
        )

        proxy_resource = apigw.CfnResource(
            self,
            f"RestApiProxyResource{cap}",
            rest_api_id=rest_api.ref,
            parent_id=rest_api.attr_root_resource_id,
            path_part="{proxy+}",
        )

        for suffix, resource_id in (
            ("Root", rest_api.attr_root_resource_id),
            ("Proxy", proxy_resource.ref),
        ):
            apigw.CfnMethod(
                self,
                f"RestApiMethodAny{suffix}{cap}",
                rest_api_id=rest_api.ref,
                resource_id=resource_id,
                http_method="ANY",
                authorization_type="NONE",
                integration=apigw.CfnMethod.IntegrationProperty(
                    type="AWS_PROXY",
                    integration_http_method="POST",
                    uri=integration_uri,
                ),
            )

        # Grant API Gateway permission to invoke the Lambda alias
        source_arn = (
            f"arn:aws:execute-api:{aws_region}:{aws_account}:{rest_api.ref}/*/*"
        )
        permission = aws_lambda.CfnPermission(
            self,
            f"BackendLambdaPermissionRestApi{cap}",
            action="lambda:InvokeFunction",
            function_name=f"{fn_name}:{stage}",
            principal="apigateway.amazonaws.com",
            source_arn=source_arn,
        )

        deployment = apigw.CfnDeployment(
            self,
            f"RestApiDeployment{cap}",
            rest_api_id=rest_api.ref,
            stage_name=stage,
            description=DESCRIPTION,
        )
        deployment.add_dependency(proxy_resource)
        deployment.add_dependency(permission)

        rest_url = f"https://{rest_api.ref}.execute-api.{aws_region}.amazonaws.com/{stage}/"
        return rest_api, rest_url

    def _make_websocket_api(
        self,
        *,
        env_name: str,
        stage: str,
        aws_region: str,
        chat_endpoint: str,
    ) -> tuple[str, str]:
        cap = stage.capitalize()

        ws_api = apigwv2.CfnApi(
            self,
            f"WsApi{cap}",
            name=f"{env_name}-websocket-{stage}",
            protocol_type="WEBSOCKET",
            route_selection_expression="$request.body.action",
            description=DESCRIPTION,
        )

        integration = apigwv2.CfnIntegration(
            self,
            f"WsIntegration{cap}",
            api_id=ws_api.ref,
            integration_type="HTTP",
            integration_method="POST",
            integration_uri=chat_endpoint,
            passthrough_behavior="WHEN_NO_MATCH",
            content_handling_strategy="CONVERT_TO_TEXT",
            payload_format_version="1.0",
            request_templates={"message_template": _WS_REQUEST_TEMPLATE},
            template_selection_expression="message_template",
            timeout_in_millis=29000,
        )

        route = apigwv2.CfnRoute(
            self,
            f"WsRoute{cap}",
            api_id=ws_api.ref,
            route_key="chat_message",
            target=f"integrations/{integration.ref}",
        )
        route.add_dependency(integration)

        ws_stage = apigwv2.CfnStage(
            self,
            f"WsStage{cap}",
            api_id=ws_api.ref,
            stage_name=stage,
            auto_deploy=True,
        )
        ws_stage.add_dependency(route)

        ws_endpoint = f"https://{ws_api.ref}.execute-api.{aws_region}.amazonaws.com"
        ws_connections = f"{ws_endpoint}/{stage}/"
        ws_url = ws_connections.replace("https://", "wss://")
        return ws_url, ws_connections
