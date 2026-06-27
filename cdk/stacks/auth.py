"""CognitoStack: Cognito user pool + app client."""

from __future__ import annotations

from aws_cdk import CfnOutput, RemovalPolicy
from aws_cdk import aws_cognito as cognito
from constructs import Construct

_LOCAL_DEV_CALLBACK_URLS = (
    "http://localhost:5173/",
    "http://localhost:5173/callback",
)


class AuthStack(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        aws_region: str,
        console_callback_urls: list[str] | None = None,
        console_logout_urls: list[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=env_name,
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        user_pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=env_name),
        )

        oauth_settings = None
        if console_callback_urls:
            oauth_settings = cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[*console_callback_urls, *_LOCAL_DEV_CALLBACK_URLS],
                logout_urls=console_logout_urls or [],
            )

        app_client = user_pool.add_client(
            "AppClient",
            user_pool_client_name=f"{env_name}_app",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
            o_auth=oauth_settings,
        )

        cognito_domain = f"{env_name}.auth.{aws_region}.amazoncognito.com"

        self.user_pool = user_pool
        self.user_pool_id = user_pool.user_pool_id
        self.user_pool_arn = user_pool.user_pool_arn
        self.app_client_id = app_client.user_pool_client_id
        self.cognito_domain = cognito_domain

        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolArn", value=user_pool.user_pool_arn)
        CfnOutput(self, "AppClientId", value=app_client.user_pool_client_id)
        CfnOutput(self, "CognitoDomain", value=cognito_domain)
