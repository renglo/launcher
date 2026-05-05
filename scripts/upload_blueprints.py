import boto3
import argparse
import os
import json
import configparser
from typing import Dict, List
from pathlib import Path

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

def get_profile_region(profile_name: str) -> str:
    """Get the region for a given AWS profile from ~/.aws/config"""
    config = configparser.ConfigParser()
    config_path = os.path.expanduser("~/.aws/config")
    
    if os.path.exists(config_path):
        config.read(config_path)
        profile_section = f"profile {profile_name}" if profile_name != "default" else "default"
        if profile_section in config and "region" in config[profile_section]:
            return config[profile_section]["region"]
    
    return "us-east-1"  # Default region if not specified

def load_blueprint_files() -> List[Dict]:
    """Load all JSON files from the blueprints directory."""
    current_dir = Path(__file__).parent
    blueprints_dir = current_dir / "blueprints"
    
    if not blueprints_dir.exists():
        raise FileNotFoundError(f"Blueprints directory not found at {blueprints_dir}")

    blueprints = []
    for json_file in blueprints_dir.glob("*.json"):
        try:
            with open(json_file, 'r') as f:
                blueprint = json.load(f)
                # Add filename (without extension) as the IRN if not present
                if 'irn' not in blueprint:
                    blueprint['irn'] = json_file.stem
                blueprints.append(blueprint)
        except json.JSONDecodeError as e:
            print(f"⚠️  Error parsing {json_file.name}: {str(e)}")
        except Exception as e:
            print(f"⚠️  Error reading {json_file.name}: {str(e)}")
    
    return blueprints

def upload_blueprints(
    dynamodb,
    table_name: str,
    blueprints: List[Dict],
    apply_changes: bool = True,
) -> Dict[str, List[str]]:
    """Upload blueprints to DynamoDB table."""
    table = dynamodb.Table(table_name)
    results = {"success": [], "failed": []}

    for blueprint in blueprints:
        try:
            # Ensure required fields exist
            if 'irn' not in blueprint:
                raise ValueError("Blueprint missing 'irn' field")
            
            # Set version to "latest" if not specified
            if 'version' not in blueprint:
                blueprint['version'] = 'latest'

            if apply_changes:
                table.put_item(Item=blueprint)
                print(f"✅ Uploaded blueprint: {blueprint['irn']}@{blueprint['version']}")
            else:
                print(f"🧪 Dry-run: blueprint would upload: {blueprint['irn']}@{blueprint['version']}")
            results["success"].append(f"{blueprint['irn']}@{blueprint['version']}")
            
        except Exception as e:
            results["failed"].append(f"{blueprint.get('irn', 'unknown')}: {str(e)}")
            print(f"❌ Failed to upload blueprint {blueprint.get('irn', 'unknown')}: {str(e)}")

    return results

def run(
    env_name: str,
    aws_profile: str,
    aws_region: str = None,
    apply_changes: bool = True,
) -> Dict[str, List[str]]:
    """Programmatic entry point that returns structured data"""
    # Get region from profile if not specified
    if aws_region is None:
        aws_region = get_profile_region(aws_profile)

    # Initialize Boto3 Session with selected profile and region
    boto3.setup_default_session(profile_name=aws_profile)
    dynamodb = boto3.resource("dynamodb", region_name=aws_region)

    print(f"🔄 Using AWS Profile: {aws_profile} in region {aws_region}")
    
    # Load blueprints from JSON files
    print("📂 Loading blueprint files...")
    blueprints = load_blueprint_files()
    print(f"📋 Found {len(blueprints)} blueprint files")

    # Upload blueprints to DynamoDB
    table_name = f"{env_name}_blueprints"
    print(f"⬆️  Uploading blueprints to table: {table_name}")
    results = upload_blueprints(dynamodb, table_name, blueprints, apply_changes=apply_changes)
    
    return results

def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description="Upload blueprint JSON files to DynamoDB.")
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
        "--aws-region",
        type=str,
        help="AWS region to use (defaults to profile's region or us-east-1)"
    )

    args = parser.parse_args()
    
    # Run the upload
    results = run(args.environment_name, args.aws_profile, args.aws_region)
    
    # Print results
    print("\n📊 Upload Summary:")
    print(f"✅ Successfully uploaded {len(results['success'])} blueprints:")
    for blueprint in results['success']:
        print(f"   • {blueprint}")
    
    if results['failed']:
        print(f"\n❌ Failed to upload {len(results['failed'])} blueprints:")
        for failure in results['failed']:
            print(f"   • {failure}")

if __name__ == "__main__":
    main() 