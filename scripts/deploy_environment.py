import argparse
from pathlib import Path
from typing import Dict, Any

import create_dynamodb_tables
import create_cognito_user_pool
import create_iam_policy
import create_iam_role
import create_s3_bucket
import create_opensearch_index
import upload_blueprints
import write_env_config
import write_created_resources


_LAUNCHER_ROOT = Path(__file__).resolve().parent.parent


class DeploymentResult:
    def __init__(self):
        self.environment_name: str = ""
        self.aws_profile: str = ""
        self.aws_region: str = ""
        self.dynamodb_tables: Dict[str, str] = {}
        self.cognito: Dict[str, str] = {}
        self.iam_policy: Dict[str, str] = {}
        self.iam_role: Dict[str, str] = {}
        self.s3: Dict[str, str] = {}
        self.opensearch: Dict[str, str] = {}
        self.status_blueprints: Dict[str, str] = {}
        self.env_config_path: str = ""
        self.resources_list_path: str = ""

def deploy_environment(
    env_name: str,
    aws_profile: str,
    aws_region: str,
) -> DeploymentResult:
    """
    Deploy all resources for an environment and return structured results
    """
    result = DeploymentResult()
    result.environment_name = env_name
    result.aws_profile = aws_profile
    result.aws_region = aws_region

    # Step 1: Create DynamoDB Tables
    print("\n📦 Creating DynamoDB tables...")
    result.dynamodb_tables = create_dynamodb_tables.run(
        env_name=env_name,
        aws_profile=aws_profile,
        region=aws_region
    )

    # Step 2: Create Cognito User Pool
    print("\n👥 Creating Cognito User Pool...")
    result.cognito = create_cognito_user_pool.run(
        env_name=env_name,
        aws_profile=aws_profile,
        aws_region=aws_region
    )

    # Step 3: Create IAM Policy
    print("\n🔒 Creating IAM Policy...")
    result.iam_policy = create_iam_policy.run(
        env_name=env_name,
        cognito_user_pool_id=result.cognito['user_pool_id'],
        aws_profile=aws_profile,
        aws_region=aws_region
    )

    # Step 4: Create S3 Bucket
    print("\n🪣 Creating S3 Bucket...")
    bucket_name = result.iam_policy.get("s3_bucket_name", result.iam_policy["s3_bucket_arn"])
    result.s3 = create_s3_bucket.run(
        bucket_name=bucket_name,
        aws_profile=aws_profile,
        aws_region=aws_region,
    )

    # Step 5: Create IAM Role
    print("\n👔 Creating IAM Role...")
    result.iam_role = create_iam_role.run(
        env_name=env_name,
        aws_profile=aws_profile,
        aws_region=aws_region
    )

    '''# Step 6: Create OpenSearch index (domain {env}-search or collection {env}-collection)
    print("\n🔍 Creating OpenSearch index...")
    try:
        result.opensearch = create_opensearch_index.run(
            env_name=env_name,
            aws_profile=aws_profile,
            aws_region=aws_region,
            lambda_role_arn=result.iam_role.get("role_arn"),
        )
    except ValueError as e:
        print(f"⚠️  OpenSearch skipped: {e}")
        result.opensearch = {}
    '''

    # Step 7: Add default Blueprints
    print("\nAdding default blueprints to DB...")
    result.status_blueprints = upload_blueprints.run(
        env_name=env_name,
        aws_profile=aws_profile,
        aws_region=aws_region
    )

    env_path = write_env_config.write_env_config_py(
        _LAUNCHER_ROOT,
        env_name,
        aws_region,
        result.cognito,
        result.s3["bucket_name"],
    )
    result.env_config_path = str(env_path)
    resources_txt_path = write_created_resources.write_created_resources_txt(
        _LAUNCHER_ROOT,
        env_name,
        {
            "dynamodb_tables": result.dynamodb_tables,
            "cognito": result.cognito,
            "iam_policy": result.iam_policy,
            "iam_role": result.iam_role,
            "s3": result.s3,
            "env_config_path": result.env_config_path,
        },
    )
    result.resources_list_path = str(resources_txt_path)

    return result

def print_deployment_summary(result: DeploymentResult):
    """Print a summary of all deployed resources"""
    print("\n✅ Environment Deployment Complete!")
    print("\nDeployment Summary")
    print("=================")
    print(f"Environment Name: {result.environment_name}")
    print(f"AWS Profile    : {result.aws_profile}")
    print(f"AWS Region     : {result.aws_region}")
    
    print("\nDynamoDB Tables")
    print("--------------")
    for table_name, table_arn in result.dynamodb_tables.items():
        print(f"Table: {table_name}")
        print(f"ARN  : {table_arn}")
    
    print("\nCognito User Pool")
    print("----------------")
    print(f"User Pool ID  : {result.cognito['user_pool_id']}")
    print(f"User Pool ARN : {result.cognito['user_pool_arn']}")
    print(f"App Client ID : {result.cognito['app_client_id']}")
    
    print("\nIAM Resources")
    print("-------------")
    print(f"Policy Name : {result.iam_policy['policy_name']}")
    print(f"Policy ARN  : {result.iam_policy['policy_arn']}")
    print(f"Role Name   : {result.iam_role['role_name']}")
    print(f"Role ARN    : {result.iam_role['role_arn']}")
    
    print("\nS3")
    print("-------------")
    print(f"Bucket Name: {result.s3.get('bucket_name', '')}")
    print(f"Bucket ARN : {result.s3.get('bucket_arn', '')}")
    print(f"Created    : {result.s3.get('created', '')}")

    if result.opensearch:
        print("\nOpenSearch")
        print("-------------")
        print(f"Endpoint : {result.opensearch['opensearch_endpoint']}")
        print(f"Index    : {result.opensearch['opensearch_index']}")

    print("\nBlueprints uploaded")
    print("-------------")
    print(f"Success : {len(result.status_blueprints['success'])} blueprints")
    print(f"Failed  : {len(result.status_blueprints['failed'])} blueprints")

    if result.env_config_path:
        print("\nenv_config.py")
        print("-------------")
        print(f"Written: {result.env_config_path}")
    if result.resources_list_path:
        print("\ncreated_resources.txt")
        print("-------------")
        print(f"Written: {result.resources_list_path}")


def main():
    parser = argparse.ArgumentParser(description="Deploy complete environment")
    parser.add_argument("environment_name", help="Name of the environment to deploy")
    parser.add_argument("--aws-profile", required=True, help="AWS profile to use (required)")
    parser.add_argument("--aws-region", default="us-east-1", help="AWS region to deploy to")

    args = parser.parse_args()

    try:
        result = deploy_environment(
            env_name=args.environment_name,
            aws_profile=args.aws_profile,
            aws_region=args.aws_region,
        )
        print_deployment_summary(result)
    except Exception as e:
        print(f"\n❌ Deployment failed: {str(e)}")
        raise

if __name__ == "__main__":
    main() 