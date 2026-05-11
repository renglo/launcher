import boto3
import argparse
import json
import random
from typing import Dict

def get_aws_account_id(session):
    """Retrieve the AWS account number dynamically."""
    sts_client = session.client("sts")
    return sts_client.get_caller_identity()["Account"]

def generate_random_number():
    """Generate an 8-digit random number."""
    return str(random.randint(10000000, 99999999))

def create_iam_policy(env_name, cognito_user_pool_id, aws_region, aws_profile):
    """Creates an IAM policy with the specified environment name and Cognito User Pool ID."""
    
    # Initialize Boto3 session with the specified profile
    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    iam_client = session.client("iam")

    # Get AWS Account ID dynamically
    aws_account_id = get_aws_account_id(session)

    # Generate a random 8-digit number for S3 bucket
    random_s3_number = generate_random_number()
    s3_bucket_arn = f"arn:aws:s3:::{env_name}-{random_s3_number}/*"
    s3_bucket_name = f"{env_name}-{random_s3_number}"

    # Define IAM Policy
    policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction"],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": ["apigateway:POST", "apigateway:GET", "apigateway:PUT", "apigateway:DELETE"],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject", "s3:ListBucket"],
                "Resource": s3_bucket_arn
            },
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": "arn:aws:logs:*:*:*"
            },
            {
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"],
                "Resource": [
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_blueprints",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_data",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_chat",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_chat/index/entity_index",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_session",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_entities",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_rel",
                    f"arn:aws:dynamodb:{aws_region}:{aws_account_id}:table/{env_name}_data/index/path_index"
                ]
            },
            {
                "Effect": "Allow",
                "Action": "ses:SendEmail",
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "cognito-idp:ListUsers",
                    "cognito-idp:AdminCreateUser",
                    "cognito-idp:AdminSetUserPassword",
                    "cognito-idp:AdminInitiateAuth",
                    "cognito-idp:RespondToAuthChallenge"
                ],
                "Resource": f"arn:aws:cognito-idp:{aws_region}:{aws_account_id}:userpool/{cognito_user_pool_id}"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "events:PutRule",
                    "events:PutTargets",
                    "events:RemoveTargets",
                    "events:DeleteRule",
                    "events:ListRules",
                    "events:DescribeRule",
                    "events:ListTargetsByRule"
                ],
                "Resource": f"arn:aws:events:{aws_region}:{aws_account_id}:rule/*"
            },
            {
                "Effect": "Allow",
                "Action": "events:PutEvents",
                "Resource": f"arn:aws:events:{aws_region}:{aws_account_id}:event-bus/default"
            },
            {
                "Effect": "Allow",
                "Action": "iam:PassRole",
                "Resource": f"arn:aws:iam::{aws_account_id}:role/*",
                "Condition": {
                    "StringEquals": {
                        "iam:PassedToService": "events.amazonaws.com"
                    }
                }
            },
            {
                "Effect": "Allow",
                "Action": [
                    "execute-api:Invoke",
                    "execute-api:ManageConnections"
                ],
                "Resource": [
                    f"arn:aws:execute-api:{aws_region}:{aws_account_id}:*/*/POST/@connections/*",
                    f"arn:aws:execute-api:{aws_region}:{aws_account_id}:*/stage/POST/_schd/ping"
                ]
            },
            {
                "Effect": "Allow",
                "Action": "aoss:APIAccessAll",
                "Resource": "*"
            }
        ]
    }

    # Policy Name
    policy_name = f"{env_name}_tt_policy"

    # Check if policy already exists
    try:
        existing_policy = iam_client.get_policy(PolicyArn=f"arn:aws:iam::{aws_account_id}:policy/{policy_name}")
        policy_arn = existing_policy["Policy"]["Arn"]
        
        # Get the current policy version
        policy_versions = iam_client.list_policy_versions(PolicyArn=policy_arn)
        current_version = next((v for v in policy_versions['Versions'] if v['IsDefaultVersion']), None)
        
        if current_version:
            # Get the current policy document
            current_policy = iam_client.get_policy_version(PolicyArn=policy_arn, VersionId=current_version['VersionId'])
            current_document = current_policy['PolicyVersion']['Document']
            
            # Check if the policy needs updating (compare with new document)
            if current_document == policy_document:
                print(f"✅ IAM Policy '{policy_name}' already exists and is up to date. Skipping creation.")
                print(f"🔹 Policy Name: {policy_name}")
                print(f"🔹 Policy ARN: {policy_arn}")
                return policy_name, policy_arn, s3_bucket_name
            else:
                print(f"🔄 IAM Policy '{policy_name}' exists but needs updating. Creating new version...")
                # Create new policy version
                iam_client.create_policy_version(
                    PolicyArn=policy_arn,
                    PolicyDocument=json.dumps(policy_document),
                    SetAsDefault=True
                )
                print(f"✅ IAM Policy '{policy_name}' updated successfully!")
                print(f"🔹 Policy Name: {policy_name}")
                print(f"🔹 Policy ARN: {policy_arn}")
                return policy_name, policy_arn, s3_bucket_name
                
    except iam_client.exceptions.NoSuchEntityException:
        # Policy doesn't exist, proceed with creation
        pass

    # Create IAM Policy
    response = iam_client.create_policy(
        PolicyName=policy_name,
        PolicyDocument=json.dumps(policy_document)
    )

    # Return created policy details
    policy_arn = response["Policy"]["Arn"]
    print(f"✅ IAM Policy Created Successfully!")
    print(f"🔹 Policy Name: {policy_name}")
    print(f"🔹 Policy ARN: {policy_arn}")

    return policy_name, policy_arn, s3_bucket_name

def run(env_name: str, cognito_user_pool_id: str, aws_profile: str, aws_region: str) -> Dict[str, str]:
    """Programmatic entry point that returns structured data"""
    policy_name, policy_arn, s3_bucket_name = create_iam_policy(
        env_name, 
        cognito_user_pool_id, 
        aws_region, 
        aws_profile
    )
    
    return {
        "policy_name": policy_name,
        "policy_arn": policy_arn,
        "s3_bucket_arn": s3_bucket_name
    }

def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description="Create an IAM policy with Cognito and S3 permissions.")
    parser.add_argument("environment_name", type=str, help="The environment name (e.g., dev, prod, test).")
    parser.add_argument("cognito_user_pool_id", type=str, help="The Cognito User Pool ID.")
    parser.add_argument("--aws-region", type=str, required=True, help="AWS region (e.g., us-east-1).")
    parser.add_argument("--aws-profile", type=str, default="default", help="AWS profile to use (default: 'default').")

    args = parser.parse_args()

    # Run the deployment
    result = run(
        args.environment_name,
        args.cognito_user_pool_id,
        args.aws_region,
        args.aws_profile
    )

    # Print results
    print("\n🎯 IAM Policy Created Successfully!\n")
    print(f"Policy Name: {result['policy_name']}")
    print(f"Policy ARN : {result['policy_arn']}")
    print(f"S3 Bucket : {result['s3_bucket_arn']}")

if __name__ == "__main__":
    main()