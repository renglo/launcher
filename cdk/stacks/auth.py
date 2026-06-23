"""CognitoStack: Cognito user pool + app client."""

from aws_cdk import CfnOutput, RemovalPolicy
from aws_cdk import aws_cognito as cognito
from constructs import Construct


class AuthStack(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
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

        app_client = user_pool.add_client(
            "AppClient",
            user_pool_client_name=f"{env_name}_app",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
        )

        self.user_pool = user_pool
        self.user_pool_id = user_pool.user_pool_id
        self.user_pool_arn = user_pool.user_pool_arn
        self.app_client_id = app_client.user_pool_client_id

        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolArn", value=user_pool.user_pool_arn)
        CfnOutput(self, "AppClientId", value=app_client.user_pool_client_id)
