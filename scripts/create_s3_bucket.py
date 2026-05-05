import argparse
from typing import Dict

import boto3
from botocore.exceptions import ClientError


def _bucket_exists(s3_client, bucket_name: str) -> bool:
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        return code in {"200", "301", "403"}


def create_s3_bucket(bucket_name: str, aws_region: str, aws_profile: str) -> Dict[str, str]:
    """Create S3 bucket if missing and return metadata."""
    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    s3_client = session.client("s3", region_name=aws_region)

    if _bucket_exists(s3_client, bucket_name):
        print(f"✅ S3 bucket '{bucket_name}' already exists. Skipping creation.")
        return {
            "bucket_name": bucket_name,
            "bucket_arn": f"arn:aws:s3:::{bucket_name}",
            "created": "false",
        }

    print(f"🛠️  Creating S3 bucket: {bucket_name}...")
    if aws_region == "us-east-1":
        s3_client.create_bucket(Bucket=bucket_name)
    else:
        s3_client.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={"LocationConstraint": aws_region},
        )

    print(f"✅ S3 bucket '{bucket_name}' created successfully.")
    return {
        "bucket_name": bucket_name,
        "bucket_arn": f"arn:aws:s3:::{bucket_name}",
        "created": "true",
    }


def run(bucket_name: str, aws_profile: str, aws_region: str) -> Dict[str, str]:
    """Programmatic entry point that returns structured data."""
    return create_s3_bucket(bucket_name, aws_region, aws_profile)


def main():
    parser = argparse.ArgumentParser(description="Create an S3 bucket if it does not exist.")
    parser.add_argument("bucket_name", type=str, help="Bucket name to create or validate")
    parser.add_argument("--aws-region", type=str, required=True, help="AWS region")
    parser.add_argument("--aws-profile", type=str, default="default", help="AWS profile")
    args = parser.parse_args()

    result = run(args.bucket_name, args.aws_profile, args.aws_region)
    print("\n🎯 S3 bucket ready!\n")
    print(f"Bucket Name : {result['bucket_name']}")
    print(f"Bucket ARN  : {result['bucket_arn']}")
    print(f"Created     : {result['created']}")


if __name__ == "__main__":
    main()
