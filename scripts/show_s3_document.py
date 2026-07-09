#!/usr/bin/env python3
"""
Show the contents of a document in an S3 bucket.
For text files (JSON, CSV, TXT, etc.) prints the content.
For binary files, prints metadata and optionally saves to a local file.

# Show a text/JSON document (prints content)
python dev/launcher/scripts/show_s3_document.py <bucket_name> <file_path>

# Show a document in _files
python dev/launcher/scripts/show_s3_document.py <bucket_name> <file_path>/thumbnail.png --save thumbnail.png

# With profile
python dev/launcher/scripts/show_s3_document.py <bucket_name> <file_path>/doc.pdf -p my-profile --save doc.pdf

"""

import argparse
import json
import sys
import boto3

def show_s3_document(
    bucket: str,
    key: str,
    profile: str | None = None,
    region: str = "us-east-1",
    save_path: str | None = None,
) -> None:
    session = boto3.Session(profile_name=profile, region_name=region)
    s3 = session.client("s3")

    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except s3.exceptions.NoSuchKey:
        print(f"Object not found: s3://{bucket}/{key}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    body = response["Body"].read()
    content_type = response.get("ContentType", "application/octet-stream")
    content_length = response.get("ContentLength", len(body))

    if save_path:
        with open(save_path, "wb") as f:
            f.write(body)
        print(f"Saved {content_length} bytes to {save_path}")
        return

    is_text = any(ct in content_type for ct in ("json", "text", "csv", "xml", "html"))
    if is_text:
        try:
            text = body.decode("utf-8")
            if "json" in content_type:
                parsed = json.loads(text)
                print(json.dumps(parsed, indent=2))
            else:
                print(text)
        except UnicodeDecodeError:
            print(f"Content-Type: {content_type}, Size: {content_length} bytes")
            print("(Binary content, use --save to download)")
    else:
        print(f"Content-Type: {content_type}")
        print(f"Size: {content_length} bytes")
        print("(Binary content, use --save to download)")


def main():
    parser = argparse.ArgumentParser(
        description="Show contents of a document in an S3 bucket.",
    )
    parser.add_argument("bucket", help="S3 bucket name")
    parser.add_argument("key", help="Object key (path)")
    parser.add_argument(
        "-s", "--save",
        metavar="FILE",
        help="Save binary content to file instead of printing",
    )
    parser.add_argument("-p", "--profile", default=None, help="AWS profile")
    parser.add_argument("-r", "--region", default="us-east-1", help="AWS region")
    args = parser.parse_args()

    show_s3_document(
        args.bucket,
        args.key,
        profile=args.profile,
        region=args.region,
        save_path=args.save,
    )


if __name__ == "__main__":
    main()
