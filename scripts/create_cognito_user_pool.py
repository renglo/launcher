import boto3
import argparse

def _find_user_pool_by_name(cognito_client, pool_name: str):
    paginator = cognito_client.get_paginator("list_user_pools")
    for page in paginator.paginate(MaxResults=60):
        for pool in page.get("UserPools", []):
            if pool.get("Name") == pool_name:
                return pool
    return None


def _find_app_client(cognito_client, user_pool_id: str, client_name: str):
    paginator = cognito_client.get_paginator("list_user_pool_clients")
    for page in paginator.paginate(UserPoolId=user_pool_id, MaxResults=60):
        for client in page.get("UserPoolClients", []):
            if client.get("ClientName") == client_name:
                return client
    return None


def create_cognito_user_pool(env_name, aws_profile, aws_region, apply_changes: bool = True):
    """Creates a Cognito User Pool and an App Client, then returns their IDs."""
    
    # Initialize Boto3 session with the specified profile
    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    cognito_client = session.client("cognito-idp")

    print(f"🛠️ Ensuring Cognito User Pool for environment: {env_name}...")
    existing_pool = _find_user_pool_by_name(cognito_client, env_name)
    if existing_pool:
        user_pool_id = existing_pool["Id"]
        user_pool_arn = cognito_client.describe_user_pool(UserPoolId=user_pool_id)["UserPool"]["Arn"]
        print(f"✅ User Pool already exists. ID: {user_pool_id}")
    else:
        if not apply_changes:
            return {"UserPoolID": "", "UserPoolARN": "", "AppClientID": ""}
        user_pool_response = cognito_client.create_user_pool(
            PoolName=env_name,
            AutoVerifiedAttributes=["email"],
            UsernameAttributes=["email"],
            Schema=[
                {
                    'Name': 'email',
                    'AttributeDataType': 'String',
                    'Required': True,
                    'Mutable': True,
                }
            ],
        )
        user_pool_id = user_pool_response["UserPool"]["Id"]
        user_pool_arn = user_pool_response["UserPool"]["Arn"]
        print(f"✅ User Pool Created! ID: {user_pool_id}")

    # Step 2: Create App Client (Single Page Application, USER_PASSWORD_AUTH)
    print(f"🛠️ Creating App Client for User Pool {user_pool_id}...")
    client_name = f"{env_name}_app"
    existing_client = _find_app_client(cognito_client, user_pool_id, client_name)
    if existing_client:
        app_client_id = existing_client["ClientId"]
        print(f"✅ App Client already exists. ID: {app_client_id}")
    else:
        if not apply_changes:
            return {"UserPoolID": user_pool_id, "UserPoolARN": user_pool_arn, "AppClientID": ""}
        app_client_response = cognito_client.create_user_pool_client(
            UserPoolId=user_pool_id,
            ClientName=client_name,
            GenerateSecret=False,
            ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
        )
        app_client_id = app_client_response["UserPoolClient"]["ClientId"]
        print(f"✅ App Client Created! ID: {app_client_id}")

    # Return results
    return {
        "UserPoolID": user_pool_id,
        "UserPoolARN": user_pool_arn,
        "AppClientID": app_client_id,
    }

def run(env_name, aws_profile, aws_region, apply_changes: bool = True):
    """Programmatic entry point that returns structured data"""
    result = create_cognito_user_pool(env_name, aws_profile, aws_region, apply_changes=apply_changes)
    return {
        "user_pool_id": result["UserPoolID"],
        "user_pool_arn": result["UserPoolARN"],
        "app_client_id": result["AppClientID"]
    }

def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description="Create an Amazon Cognito User Pool and App Client.")
    
    parser.add_argument("environment_name", type=str, help="The environment name (e.g., dev, prod, test).")
    parser.add_argument("--aws-profile", type=str, default="default", help="AWS profile to use (default: 'default').")
    parser.add_argument("--aws-region", type=str, required=True, help="AWS region (e.g., us-east-1).")

    args = parser.parse_args()

    # Run the function
    result = run(args.environment_name, args.aws_profile, args.aws_region)

    # Print the results in CLI format
    print("\n🎯 Cognito User Pool & App Client Created Successfully!\n")
    print(f"UserPoolID   : {result['user_pool_id']}")
    print(f"UserPoolARN  : {result['user_pool_arn']}")
    print(f"AppClientID  : {result['app_client_id']}")

if __name__ == "__main__":
    main()