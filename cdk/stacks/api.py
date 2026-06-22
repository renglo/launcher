"""ApiStack: REST API Gateway (proxy) + WebSocket API Gateway per stage.

REST integrations target backend Lambda alias ARNs by convention. The Lambda
functions are created by the releases-repo OIDC pipeline (not CloudFormation).
Lambda invoke permissions are added by that pipeline on first deploy.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_apigatewayv2 as apigwv2
from constructs import Construct

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

DESCRIPTION = "Reglo Deployment"


def backend_alias_arn(env_name: str, stage: str, region: str, account: str) -> str:
    fn_name = f"{env_name}-backend-{stage}"
    return f"arn:aws:lambda:{region}:{account}:function:{fn_name}:{stage}"


class ApiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        aws_region: str,
        aws_account: str,
        prod_alias_arn: str,
        staging_alias_arn: str = "",
        enable_staging: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        prod_rest_url, prod_ws_url, prod_ws_connections = self._make_stage_apis(
            env_name=env_name,
            stage="production",
            alias_arn=prod_alias_arn,
            aws_region=aws_region,
        )

        staging_rest_url = staging_ws_url = staging_ws_connections = ""
        if enable_staging and staging_alias_arn:
            staging_rest_url, staging_ws_url, staging_ws_connections = self._make_stage_apis(
                env_name=env_name,
                stage="staging",
                alias_arn=staging_alias_arn,
                aws_region=aws_region,
            )

        self.prod_rest_url = prod_rest_url
        self.prod_ws_url = prod_ws_url
        self.prod_ws_connections = prod_ws_connections

        CfnOutput(self, "RestApiUrlProduction", value=prod_rest_url)
        CfnOutput(self, "WebSocketUrlProduction", value=prod_ws_url)
        CfnOutput(self, "WebSocketConnectionsUrlProduction", value=prod_ws_connections)
        if enable_staging and staging_alias_arn:
            CfnOutput(self, "RestApiUrlStaging", value=staging_rest_url)
            CfnOutput(self, "WebSocketUrlStaging", value=staging_ws_url)
            CfnOutput(self, "WebSocketConnectionsUrlStaging", value=staging_ws_connections)

    def _make_stage_apis(
        self,
        *,
        env_name: str,
        stage: str,
        alias_arn: str,
        aws_region: str,
    ) -> tuple[str, str, str]:
        stage_cap = stage.capitalize()
        integration_uri = (
            f"arn:aws:apigateway:{aws_region}:lambda:path/2015-03-31/functions/"
            f"{alias_arn}/invocations"
        )

        rest_api = apigw.CfnRestApi(
            self,
            f"RestApi{stage_cap}",
            name=f"{env_name}-api-{stage}",
            description=DESCRIPTION,
        )

        proxy_resource = apigw.CfnResource(
            self,
            f"RestApiProxyResource{stage_cap}",
            rest_api_id=rest_api.ref,
            parent_id=rest_api.attr_root_resource_id,
            path_part="{proxy+}",
        )

        lambda_integration = apigw.CfnMethod.IntegrationProperty(
            type="AWS_PROXY",
            integration_http_method="POST",
            uri=integration_uri,
        )
        root_method = apigw.CfnMethod(
            self,
            f"RestApiMethodAnyRoot{stage_cap}",
            rest_api_id=rest_api.ref,
            resource_id=rest_api.attr_root_resource_id,
            http_method="ANY",
            authorization_type="NONE",
            integration=lambda_integration,
        )
        proxy_method = apigw.CfnMethod(
            self,
            f"RestApiMethodAnyProxy{stage_cap}",
            rest_api_id=rest_api.ref,
            resource_id=proxy_resource.ref,
            http_method="ANY",
            authorization_type="NONE",
            integration=lambda_integration,
        )

        # Deployment must run after all methods exist or the stage snapshot omits /{proxy+}.
        deployment = apigw.CfnDeployment(
            self,
            f"RestApiDeployment{stage_cap}",
            rest_api_id=rest_api.ref,
            description=DESCRIPTION,
        )
        deployment.add_dependency(proxy_resource)
        deployment.add_dependency(root_method)
        deployment.add_dependency(proxy_method)

        apigw.CfnStage(
            self,
            f"RestApiStage{stage_cap}",
            rest_api_id=rest_api.ref,
            deployment_id=deployment.ref,
            stage_name=stage,
            description=DESCRIPTION,
        )

        rest_url = f"https://{rest_api.ref}.execute-api.{aws_region}.amazonaws.com/{stage}/"
        chat_endpoint = f"{rest_url}_chat/message"

        ws_api = apigwv2.CfnApi(
            self,
            f"WsApi{stage_cap}",
            name=f"{env_name}-websocket-{stage}",
            protocol_type="WEBSOCKET",
            route_selection_expression="$request.body.action",
            description=DESCRIPTION,
        )

        integration = apigwv2.CfnIntegration(
            self,
            f"WsIntegration{stage_cap}",
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
            f"WsRoute{stage_cap}",
            api_id=ws_api.ref,
            route_key="chat_message",
            target=f"integrations/{integration.ref}",
        )
        route.add_dependency(integration)

        ws_stage = apigwv2.CfnStage(
            self,
            f"WsStage{stage_cap}",
            api_id=ws_api.ref,
            stage_name=stage,
            auto_deploy=True,
        )
        ws_stage.add_dependency(route)

        ws_endpoint = f"https://{ws_api.ref}.execute-api.{aws_region}.amazonaws.com"
        ws_connections_url = f"{ws_endpoint}/{stage}/"
        ws_url = ws_connections_url.replace("https://", "wss://")

        return rest_url, ws_url, ws_connections_url
