"""Create or update API Gateway WebSocket APIs (routes, integrations, stage)."""

from __future__ import annotations

import argparse
import configparser
import json
import os
import sys
from typing import Dict, Optional

import boto3


REGLO_DEPLOYMENT_DESCRIPTION = "Reglo Deployment"
DEFAULT_ROUTE = "chat_message"


def log(message: str) -> None:
    """Write human-readable logs to stderr to keep stdout machine-readable."""
    print(message, file=sys.stderr)


def get_available_aws_profiles():
    """Retrieve available AWS profiles from ~/.aws/credentials and ~/.aws/config."""
    profiles = []
    aws_credentials_path = os.path.expanduser("~/.aws/credentials")
    aws_config_path = os.path.expanduser("~/.aws/config")

    if os.path.exists(aws_credentials_path):
        config = configparser.ConfigParser()
        config.read(aws_credentials_path)
        profiles.extend(config.sections())

    if os.path.exists(aws_config_path):
        config = configparser.ConfigParser()
        config.read(aws_config_path)
        for section in config.sections():
            if section.startswith("profile "):
                profile_name = section.replace("profile ", "")
                if profile_name not in profiles:
                    profiles.append(profile_name)

    return profiles if profiles else ["default"]


def api_exists(apigw, api_name: str) -> str:
    """Check if a WebSocket API exists and return its ID if found."""
    try:
        response = apigw.get_apis()
        for api in response.get("Items", []):
            if api["Name"] == api_name and api["ProtocolType"] == "WEBSOCKET":
                return api["ApiId"]
        return ""
    except Exception as e:
        log(f"Error checking API existence: {e}")
        return ""


def find_route(apigw, api_id: str, route_key: str) -> Optional[Dict]:
    """Find a route by key."""
    try:
        response = apigw.get_routes(ApiId=api_id)
        for route in response.get("Items", []):
            if route.get("RouteKey") == route_key:
                return route
    except Exception as e:
        log(f"Error finding route '{route_key}': {e}")
    return None


def find_stage(apigw, api_id: str, stage_name: str) -> Optional[Dict]:
    """Find stage by name."""
    try:
        response = apigw.get_stages(ApiId=api_id)
        for stage in response.get("Items", []):
            if stage.get("StageName") == stage_name:
                return stage
    except Exception as e:
        log(f"Error finding stage '{stage_name}': {e}")
    return None


def create_or_replace_integration(
    apigw, api_id: str, route_key: str, integration_uri: str, old_integration_id: Optional[str] = None
) -> Dict:
    """Always create a fresh integration, then optionally delete the previous one."""
    integration = create_integration(apigw, api_id, route_key, integration_uri)
    if old_integration_id:
        try:
            apigw.delete_integration(ApiId=api_id, IntegrationId=old_integration_id)
        except Exception:
            pass
    return integration


def upsert_route_with_integration(apigw, api_id: str, route_key: str, integration_target: str) -> None:
    """Create/update route and point it to a fresh integration."""
    existing_route = find_route(apigw, api_id, route_key)
    old_integration_id = None
    if existing_route:
        target = existing_route.get("Target", "")
        if target.startswith("integrations/"):
            old_integration_id = target.split("/", 1)[1]
        route_id = existing_route["RouteId"]
    else:
        route_response = create_route(apigw, api_id, route_key)
        route_id = route_response["RouteId"]

    integration_response = create_or_replace_integration(
        apigw, api_id, route_key, integration_target, old_integration_id
    )
    integration_id = integration_response["IntegrationId"]
    update_route(apigw, api_id, route_id, route_key, integration_id)


def create_websocket_api(apigw, api_name: str, route_selection_expr: str) -> Dict:
    """Create a WebSocket API."""
    log(f"Creating WebSocket API: {api_name}...")

    try:
        response = apigw.create_api(
            Name=api_name,
            ProtocolType="WEBSOCKET",
            RouteSelectionExpression=route_selection_expr,
            Description=REGLO_DEPLOYMENT_DESCRIPTION,
        )
        log(f"WebSocket API '{api_name}' created successfully.")
        return response
    except Exception as e:
        log(f"Error creating WebSocket API: {e}")
        raise


def create_route(apigw, api_id: str, route_key: str) -> Dict:
    """Create a route for the WebSocket API."""
    try:
        return apigw.create_route(ApiId=api_id, RouteKey=route_key)
    except Exception as e:
        log(f"Error creating route '{route_key}': {e}")
        raise


def update_route(apigw, api_id: str, route_id: str, route_key: str, integration_id: str) -> Dict:
    """Update a route to point to an integration."""
    try:
        return apigw.update_route(
            ApiId=api_id,
            RouteId=route_id,
            RouteKey=route_key,
            Target=f"integrations/{integration_id}",
        )
    except Exception as e:
        log(f"Error updating route target: {e}")
        raise


def create_integration(apigw, api_id: str, route_key: str, integration_uri: str) -> Dict:
    """Create an HTTP integration for the WebSocket API."""
    try:
        cleaned_uri = integration_uri.lstrip("@")
        request_template = """#set($action = $input.path('$.action'))
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
        return apigw.create_integration(
            ApiId=api_id,
            IntegrationType="HTTP",
            IntegrationMethod="POST",
            IntegrationUri=cleaned_uri,
            PassthroughBehavior="WHEN_NO_MATCH",
            ContentHandlingStrategy="CONVERT_TO_TEXT",
            IntegrationResponseSelectionExpression="${integration.response.statuscode}",
            PayloadFormatVersion="1.0",
            RequestTemplates={"message_template": request_template},
            TemplateSelectionExpression="message_template",
            TimeoutInMillis=29000,
        )
    except Exception as e:
        log(f"Error creating integration for route '{route_key}': {e}")
        raise


def create_stage(apigw, api_id: str, stage_name: str) -> Dict:
    """Create a stage for the WebSocket API."""
    try:
        return apigw.create_stage(ApiId=api_id, StageName=stage_name, AutoDeploy=True)
    except Exception as e:
        log(f"Error creating stage '{stage_name}': {e}")
        raise


def ensure_stage(apigw, api_id: str, stage_name: str) -> Dict:
    """Create stage if missing; otherwise keep existing stage."""
    existing_stage = find_stage(apigw, api_id, stage_name)
    if existing_stage:
        return existing_stage
    return create_stage(apigw, api_id, stage_name)


def run(
    api_name: str,
    route: str,
    integration_target: str,
    stage_name: str,
    aws_profile: Optional[str] = None,
    region: str = "us-east-1",
) -> Dict[str, str]:
    """Create or update WebSocket API; return URLs and ids."""
    if aws_profile:
        boto3.setup_default_session(profile_name=aws_profile, region_name=region)
    else:
        boto3.setup_default_session(region_name=region)
    apigw = boto3.client("apigatewayv2", region_name=region)
    route_selection_expr = "$request.body.action"

    existing_api_id = api_exists(apigw, api_name)
    if existing_api_id:
        api = apigw.get_api(ApiId=existing_api_id)
        api_id = existing_api_id
    else:
        api = create_websocket_api(apigw, api_name, route_selection_expr)
        api_id = api["ApiId"]

    upsert_route_with_integration(apigw, api_id, route, integration_target)
    ensure_stage(apigw, api_id, stage_name)

    api_endpoint = api.get("ApiEndpoint", "")
    stage_url = f"{api_endpoint}/{stage_name}/"
    websocket_url = stage_url.replace("https://", "wss://")
    return {
        "api_id": api_id,
        "api_endpoint": api_endpoint,
        "stage_url": stage_url,
        "websocket_url": websocket_url,
        "connections_url": stage_url,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create WebSocket API for a given environment.")
    parser.add_argument("api_name", type=str, help="The full WebSocket API name.")
    parser.add_argument("integration_target", type=str, help="The integration target URL.")
    parser.add_argument("stage_name", type=str, help="The stage name (e.g., production).")
    parser.add_argument("--route", type=str, default=DEFAULT_ROUTE, help="Custom route key.")
    available_profiles = get_available_aws_profiles()
    parser.add_argument(
        "--aws-profile",
        type=str,
        choices=available_profiles + [""],
        default="",
        help=f"AWS profile (empty = environment credentials). Available: {', '.join(available_profiles)}",
    )
    parser.add_argument("--region", type=str, default="us-east-1", help="AWS region (default: us-east-1)")
    parser.add_argument("--json-output", action="store_true", help="Print machine-readable JSON only.")
    args = parser.parse_args()

    result = run(
        args.api_name,
        args.route,
        args.integration_target,
        args.stage_name,
        args.aws_profile or None,
        args.region,
    )
    if args.json_output:
        print(json.dumps(result))
    else:
        print(f"API ID: {result['api_id']}")
        print(f"WebSocket URL: {result['websocket_url']}")
        print(f"Connections URL: {result['connections_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())