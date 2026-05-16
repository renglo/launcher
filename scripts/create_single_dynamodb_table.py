import boto3
import argparse
import os
import configparser
from typing import Dict, Optional

'''
USAGE

python create_single_dynamodb_table.py --table-name noma_chat3 --partition-key index --sort-key entities_id --aws-profile maker --region us-east-1
'''


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


def table_exists(dynamodb, table_name: str) -> bool:
    """Check if a DynamoDB table exists."""
    try:
        dynamodb.describe_table(TableName=table_name)
        return True
    except dynamodb.exceptions.ResourceNotFoundException:
        return False


def create_empty_table(
    dynamodb,
    table_name: str,
    partition_key: str,
    sort_key: Optional[str] = None,
):
    """Create a single empty DynamoDB table with on-demand billing."""
    if table_exists(dynamodb, table_name):
        print(f"✅ Table '{table_name}' already exists. Skipping creation.")
        return

    print(f"Creating table: {table_name}...")

    key_schema = [{"AttributeName": partition_key, "KeyType": "HASH"}]  # Partition Key
    attribute_definitions = [{"AttributeName": partition_key, "AttributeType": "S"}]  # String type

    if sort_key:
        key_schema.append({"AttributeName": sort_key, "KeyType": "RANGE"})  # Sort Key
        attribute_definitions.append({"AttributeName": sort_key, "AttributeType": "S"})  # String type

    table_params = {
        "TableName": table_name,
        "KeySchema": key_schema,
        "AttributeDefinitions": attribute_definitions,
        "BillingMode": "PAY_PER_REQUEST",
    }

    dynamodb.create_table(**table_params)
    print(f"⏳ Waiting for table '{table_name}' to become active...")

    waiter = dynamodb.get_waiter("table_exists")
    waiter.wait(TableName=table_name)
    print(f"✅ Table '{table_name}' is now active.")


def run(
    table_name: str,
    partition_key: str,
    sort_key: Optional[str],
    aws_profile: str,
    region: str = "us-east-1",
) -> Dict[str, str]:
    """Programmatic entry point that creates one table and returns its ARN."""
    boto3.setup_default_session(profile_name=aws_profile)
    dynamodb = boto3.client("dynamodb", region_name=region)

    print(f"🔄 Using AWS Profile: {aws_profile} in region {region}")

    create_empty_table(dynamodb, table_name, partition_key, sort_key)
    response = dynamodb.describe_table(TableName=table_name)
    table_arn = response["Table"]["TableArn"]
    return {table_name: table_arn}


def main():
    """CLI entry point to create a single DynamoDB table."""
    parser = argparse.ArgumentParser(
        description=(
            "Create a single DynamoDB table with the given partition and optional sort key."
        )
    )
    parser.add_argument("--table-name", type=str, required=True, help="Table name")
    parser.add_argument("--partition-key", type=str, required=True, help="Partition key attribute name")
    parser.add_argument("--sort-key", type=str, default=None, help="Optional sort key attribute name")

    available_profiles = get_available_aws_profiles()
    parser.add_argument(
        "--aws-profile",
        type=str,
        choices=available_profiles,
        default="default",
        help=f"Specify the AWS profile to use (Available: {', '.join(available_profiles)})",
    )
    parser.add_argument(
        "--region",
        type=str,
        default="us-east-1",
        help="AWS region to create the table in (default: us-east-1)",
    )

    args = parser.parse_args()

    table_arns = run(
        table_name=args.table_name,
        partition_key=args.partition_key,
        sort_key=args.sort_key,
        aws_profile=args.aws_profile,
        region=args.region,
    )

    print("\n✅ DynamoDB Table Created Successfully!\n")
    for table_name, table_arn in table_arns.items():
        print(f"Table: {table_name}")
        print(f"ARN  : {table_arn}\n")


if __name__ == "__main__":
    main()




