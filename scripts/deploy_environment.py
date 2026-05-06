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
import write_extension_install_config
from bootstrap_github_oidc import BootstrapConfig, run as bootstrap_github_oidc
from provision_backend_infra import BackendProvisionConfig, run as provision_backend_infra


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
        self.bootstrap: Dict[str, Any] = {}
        self.backend: Dict[str, Any] = {}
        self.env_config_path: str = ""
        self.resources_list_path: str = ""
        self.extension_install_path: str = ""

def deploy_environment(
    env_name: str,
    aws_profile: str,
    aws_region: str,
    github_repo: str,
    enable_staging_role: bool = True,
    skip_cdk_bootstrap: bool = True,
    seed_image_uri: str = "",
    dry_run: bool = False,
) -> DeploymentResult:
    """
    Deploy all resources for an environment and return structured results
    """
    result = DeploymentResult()
    result.environment_name = env_name
    result.aws_profile = aws_profile
    result.aws_region = aws_region

    # Step 1: Bootstrap GitHub OIDC + deploy roles
    print("\n🔐 Bootstrapping GitHub OIDC + deploy roles...")
    result.bootstrap = bootstrap_github_oidc(
        BootstrapConfig(
            env_name=env_name,
            aws_profile=aws_profile,
            aws_region=aws_region,
            github_repo=github_repo,
            enable_staging_role=enable_staging_role,
            skip_cdk_bootstrap=skip_cdk_bootstrap,
            apply_changes=not dry_run,
        )
    )

    # Step 2: Create DynamoDB Tables
    print("\n📦 Creating DynamoDB tables...")
    result.dynamodb_tables = create_dynamodb_tables.run(
        env_name=env_name,
        aws_profile=aws_profile,
        region=aws_region,
        apply_changes=not dry_run,
    )

    # Step 3: Create Cognito User Pool
    print("\n👥 Creating Cognito User Pool...")
    result.cognito = create_cognito_user_pool.run(
        env_name=env_name,
        aws_profile=aws_profile,
        aws_region=aws_region,
        apply_changes=not dry_run,
    )

    # Step 4: Create IAM Policy
    print("\n🔒 Creating IAM Policy...")
    result.iam_policy = create_iam_policy.run(
        env_name=env_name,
        cognito_user_pool_id=result.cognito['user_pool_id'],
        aws_profile=aws_profile,
        aws_region=aws_region,
        apply_changes=not dry_run,
    )

    # Step 5: Create S3 Bucket
    print("\n🪣 Creating S3 Bucket...")
    bucket_name = result.iam_policy.get("s3_bucket_name", result.iam_policy["s3_bucket_arn"])
    result.s3 = create_s3_bucket.run(
        bucket_name=bucket_name,
        aws_profile=aws_profile,
        aws_region=aws_region,
        apply_changes=not dry_run,
    )

    # Step 6: Create IAM Role
    print("\n👔 Creating IAM Role...")
    result.iam_role = create_iam_role.run(
        env_name=env_name,
        aws_profile=aws_profile,
        aws_region=aws_region,
        apply_changes=not dry_run,
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

    # Step 7: Provision backend infra (one-time) for production + staging
    print("\n🚀 Provisioning backend infra (production)...")
    backend_production = provision_backend_infra(
        BackendProvisionConfig(
            env_name=env_name,
            aws_profile=aws_profile,
            aws_region=aws_region,
            lambda_role_arn=result.iam_role["role_arn"],
            stage_name="production",
            seed_image_uri=seed_image_uri,
            apply_changes=not dry_run,
        )
    )
    print("\n🚀 Provisioning backend infra (staging)...")
    backend_staging = provision_backend_infra(
        BackendProvisionConfig(
            env_name=env_name,
            aws_profile=aws_profile,
            aws_region=aws_region,
            lambda_role_arn=result.iam_role["role_arn"],
            stage_name="staging",
            seed_image_uri=seed_image_uri,
            apply_changes=not dry_run,
        )
    )
    result.backend = {
        "production": backend_production,
        "staging": backend_staging,
    }

    # Step 8: Add default Blueprints
    print("\nAdding default blueprints to DB...")
    result.status_blueprints = upload_blueprints.run(
        env_name=env_name,
        aws_profile=aws_profile,
        aws_region=aws_region,
        apply_changes=not dry_run,
    )

    env_path = write_env_config.write_env_config_py(
        _LAUNCHER_ROOT,
        env_name,
        aws_region,
        result.cognito,
        result.s3["bucket_name"],
        websocket_connections=backend_production.get("websocket", {}).get("connections_url", ""),
        vite_websocket_url=backend_production.get("websocket", {}).get("websocket_url", ""),
        websocket_connections_staging=backend_staging.get("websocket", {}).get("connections_url", ""),
        vite_websocket_url_staging=backend_staging.get("websocket", {}).get("websocket_url", ""),
    )
    result.env_config_path = str(env_path)
    extension_install_path = write_extension_install_config.write_extension_install_json(
        _LAUNCHER_ROOT,
        env_name,
        result.bootstrap,
    )
    result.extension_install_path = str(extension_install_path)
    resources_txt_path = write_created_resources.write_created_resources_txt(
        _LAUNCHER_ROOT,
        env_name,
        {
            "dynamodb_tables": result.dynamodb_tables,
            "cognito": result.cognito,
            "iam_policy": result.iam_policy,
            "iam_role": result.iam_role,
            "s3": result.s3,
            "backend": result.backend,
            "env_config_path": result.env_config_path,
            "extension_install_path": result.extension_install_path,
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
    if result.bootstrap:
        print("\nGitHub OIDC Bootstrap")
        print("---------------------")
        print(f"OIDC Provider : {result.bootstrap.get('oidc_provider_arn', '')}")
        print(f"Role (prod)   : {result.bootstrap.get('role_arn_production', '')}")
        print(f"Role (staging): {result.bootstrap.get('role_arn_staging', '')}")
    
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

    if result.backend:
        print("\nBackend Infra")
        print("-------------")
        for stage_name in ("production", "staging"):
            stage_backend = result.backend.get(stage_name, {})
            if not isinstance(stage_backend, dict):
                continue
            print(f"Stage      : {stage_name}")
            ecr_info = stage_backend.get("ecr", {})
            print(f"ECR Repo   : {ecr_info.get('repository_name', '')}")
            lambda_info = stage_backend.get("lambda", {})
            alias_info = stage_backend.get("alias", {})
            print(f"Lambda     : {lambda_info.get('function_name', '')}")
            print(f"Alias      : {alias_info.get('alias_name', '')}")
            ws_info = stage_backend.get("websocket", {})
            print(f"WebSocket  : {ws_info.get('websocket_url', '')}")

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
    if result.extension_install_path:
        print("\nextension_install.json")
        print("-------------")
        print(f"Written: {result.extension_install_path}")


def main():
    parser = argparse.ArgumentParser(description="Deploy complete environment")
    parser.add_argument("environment_name", help="Name of the environment to deploy")
    parser.add_argument("--aws-profile", required=True, help="AWS profile to use (required)")
    parser.add_argument("--aws-region", default="us-east-1", help="AWS region to deploy to")
    parser.add_argument("--github-repo", required=True, help="GitHub org/repo for OIDC trust policy")
    parser.add_argument("--disable-staging-role", action="store_true", help="Disable staging GitHub OIDC role")
    parser.add_argument(
        "--enable-cdk-bootstrap",
        action="store_true",
        help="Run CDK bootstrap (optional now; required later if/when using CDK deploy flows).",
    )
    parser.add_argument(
        "--seed-image-uri",
        default="",
        help="ECR image URI used only when backend Lambda is created for the first time.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan IAM/backend changes without creating resources")

    args = parser.parse_args()

    try:
        result = deploy_environment(
            env_name=args.environment_name,
            aws_profile=args.aws_profile,
            aws_region=args.aws_region,
            github_repo=args.github_repo,
            enable_staging_role=not args.disable_staging_role,
            skip_cdk_bootstrap=not args.enable_cdk_bootstrap,
            seed_image_uri=args.seed_image_uri,
            dry_run=args.dry_run,
        )
        print_deployment_summary(result)
    except Exception as e:
        print(f"\n❌ Deployment failed: {str(e)}")
        raise

if __name__ == "__main__":
    main() 