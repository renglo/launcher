#!/usr/bin/env python3
"""
List the contents of a virtual folder (prefix) in an S3 bucket.

# List objects under a prefix
python dev/launcher/scripts/list_s3_prefix.py <bucket_name> <path>

# Long format (size, last modified, key)
python dev/launcher/scripts/list_s3_prefix.py <bucket_name> <path> -l

# With profile
python dev/launcher/scripts/list_s3_prefix.py <bucket_name> <path> -p my-profile

"""

import argparse
import boto3


def list_s3_prefix(
    bucket: str,
    prefix: str,
    profile: str | None = None,
    region: str = "us-east-1",
    long_format: bool = False,
) -> None:
    session = boto3.Session(profile_name=profile, region_name=region)
    s3 = session.client("s3")

    prefix = prefix.rstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"

    paginator = s3.get_paginator("list_objects_v2")
    count = 0

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            count += 1
            if long_format:
                size = obj.get("Size", 0)
                last_modified = obj.get("LastModified")
                lm_str = last_modified.strftime("%Y-%m-%d %H:%M") if last_modified else "-"
                print(f"{size:>12}  {lm_str}  {key}")
            else:
                print(key)

    if count == 0:
        print(f"No objects found under s3://{bucket}/{prefix}")


def main():
    parser = argparse.ArgumentParser(
        description="List contents of a virtual folder (prefix) in an S3 bucket.",
    )
    parser.add_argument("bucket", help="S3 bucket name")
    parser.add_argument("prefix", help="Prefix (folder path), e.g. _files/portfolio/org/_thumbnails")
    parser.add_argument(
        "-l", "--long",
        action="store_true",
        help="Long format: size, last modified, key",
    )
    parser.add_argument("-p", "--profile", default=None, help="AWS profile")
    parser.add_argument("-r", "--region", default="us-east-1", help="AWS region")
    args = parser.parse_args()

    list_s3_prefix(
        args.bucket,
        args.prefix,
        profile=args.profile,
        region=args.region,
        long_format=args.long,
    )


if __name__ == "__main__":
    main()
