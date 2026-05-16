import boto3
import argparse
import os
import configparser
from typing import Dict

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

def table_exists(dynamodb, table_name):
    """Check if a DynamoDB table exists."""
    try:
        dynamodb.describe_table(TableName=table_name)
        return True
    except dynamodb.exceptions.ResourceNotFoundException:
        return False

def create_table(dynamodb, table_name, partition_key, sort_key=None, local_secondary_indexes=None, apply_changes=True):
    """Create a DynamoDB table with optional LSI indexes."""
    if table_exists(dynamodb, table_name):
        print(f"✅ Table '{table_name}' already exists. Skipping creation.")
        return

    if not apply_changes:
        print(f"Dry-run: table '{table_name}' would be created.")
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

    # Add Local Secondary Indexes if provided
    if local_secondary_indexes:
        table_params["LocalSecondaryIndexes"] = []
        for index in local_secondary_indexes:
            projection = {"ProjectionType": index["ProjectionType"]}
            if index["ProjectionType"] == "INCLUDE":
                projection["NonKeyAttributes"] = index.get("NonKeyAttributes", [])
                
            table_params["LocalSecondaryIndexes"].append({
                "IndexName": index["IndexName"],
                "KeySchema": [
                    {"AttributeName": partition_key, "KeyType": "HASH"},
                    {"AttributeName": index["SortKey"], "KeyType": "RANGE"},
                ],
                "Projection": projection,
            })
            attribute_definitions.append({"AttributeName": index["SortKey"], "AttributeType": "S"})

    dynamodb.create_table(**table_params)
    print(f"⏳ Waiting for table '{table_name}' to become active...")

    waiter = dynamodb.get_waiter("table_exists")
    waiter.wait(TableName=table_name)
    print(f"✅ Table '{table_name}' is now active.")

def run(env_name: str, aws_profile: str, region: str = "us-east-1", apply_changes: bool = True) -> Dict[str, str]:
    """Programmatic entry point that returns structured data"""
    # Initialize Boto3 Session with selected profile
    boto3.setup_default_session(profile_name=aws_profile)
    dynamodb = boto3.client("dynamodb", region_name=region)

    print(f"🔄 Using AWS Profile: {aws_profile} in region {region}")

    # Define tables and their keys
    tables = [
        {"name": f"{env_name}_blueprints", "partition_key": "irn", "sort_key": "version"},
        {"name": f"{env_name}_entities", "partition_key": "index", "sort_key": "_id"},
        {"name": f"{env_name}_rel", "partition_key": "index", "sort_key": "rel"},
        {"name": f"{env_name}_chat", "partition_key": "index", "sort_key": "entity_index"},
    ]

    # Create tables and collect ARNs
    table_arns = {}
    
    # Create standard tables
    for table in tables:
        
        create_table(dynamodb, table["name"], table["partition_key"], table["sort_key"], apply_changes=apply_changes)
        if table_exists(dynamodb, table["name"]):
            response = dynamodb.describe_table(TableName=table["name"])
            table_arns[table["name"]] = response["Table"]["TableArn"]
        else:
            table_arns[table["name"]] = ""

    # Create data table with LSIs
    data_table_name = f"{env_name}_data"
    data_table_lsis = [
        {"IndexName": "geo_index", "SortKey": "geo_index", "ProjectionType": "KEYS_ONLY"},
        {"IndexName": "path_index", "SortKey": "path_index", "ProjectionType": "ALL"},
        {"IndexName": "time_index", "SortKey": "time_index", "ProjectionType": "INCLUDE", "NonKeyAttributes": ["path_index"]},
    ]
    
    create_table(
        dynamodb,
        data_table_name,
        "portfolio_index",
        "doc_index",
        local_secondary_indexes=data_table_lsis,
        apply_changes=apply_changes,
    )
    if table_exists(dynamodb, data_table_name):
        response = dynamodb.describe_table(TableName=data_table_name)
        table_arns[data_table_name] = response["Table"]["TableArn"]
    else:
        table_arns[data_table_name] = ""

    return table_arns

def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description="Create DynamoDB tables for a given environment.")
    parser.add_argument("environment_name", type=str, help="The environment name (e.g., dev, prod, test).")
    
    available_profiles = get_available_aws_profiles()
    parser.add_argument(
        "--aws-profile",
        type=str,
        choices=available_profiles,
        default="default",
        help=f"Specify the AWS profile to use (Available: {', '.join(available_profiles)})"
    )
    parser.add_argument(
        "--region",
        type=str,
        default="us-east-1",
        help="AWS region to create the tables in (default: us-east-1)"
    )

    args = parser.parse_args()
    
    # Run the deployment
    table_arns = run(args.environment_name, args.aws_profile, args.region)
    
    # Print results
    print("\n✅ DynamoDB Tables Created Successfully!\n")
    for table_name, table_arn in table_arns.items():
        print(f"Table: {table_name}")
        print(f"ARN  : {table_arn}\n")

if __name__ == "__main__":
    main()