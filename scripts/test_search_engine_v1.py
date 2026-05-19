import argparse
import configparser
import os
import uuid
from typing import Dict

import boto3


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


def run(
    env_name: str,
    aws_profile: str,
    region: str = "us-east-1",
    portfolio: str = "test_portfolio",
    org: str = "test_org",
    ring: str = "test_ring",
) -> Dict[str, object]:
    """
    Smoke test:
    1) index one document
    2) search for a known token
    3) delete document index rows
    4) confirm search returns zero
    """
    boto3.setup_default_session(profile_name=aws_profile)

    try:
        from renglo.search.search_controller import SearchController
    except ImportError as exc:
        raise RuntimeError(
            "Could not import 'renglo'. Install/activate the environment where renglo is pip installed."
        ) from exc

    search_table_name = f"{env_name}_search"
    config = {
        "AWS_REGION": region,
        "DYNAMODB_SEARCH_TABLE": search_table_name,
    }

    controller = SearchController(config=config)
    if not controller.is_enabled():
        raise RuntimeError("SearchController is disabled. Check DYNAMODB_SEARCH_TABLE config.")

    doc_id = f"smoke-{uuid.uuid4().hex[:12]}"
    unique_token = f"ultra{uuid.uuid4().hex[:10]}"
    sample_doc = {
        "_id": doc_id,
        "attributes": {
            "title": f"Search smoke document {unique_token}",
            "notes": "This note validates DynamoDB reverse index search flow.",
            "sku_code": "AB1",  # short token field exception
        },
        "modified": "2026-05-19T00:00:00Z",
    }

    print(f"🔄 Using AWS Profile: {aws_profile} in region {region}")
    print(f"📌 Using search table: {search_table_name}")
    print(f"🧪 Testing with doc_id: {doc_id}")
    print(f"🔎 Unique token: {unique_token}")

    index_result = controller.index_document(portfolio, org, ring, sample_doc)
    print(f"✅ Index result: {index_result}")

    search_result_before = controller.search(
        portfolio=portfolio,
        org=org,
        query=unique_token,
        datatypes=[ring],
        limit=10,
        offset=0,
    )
    before_total = int(search_result_before.get("total", 0))
    print(f"✅ Search-before-delete total: {before_total}")

    delete_result = controller.delete_document(portfolio, org, ring, doc_id)
    print(f"✅ Delete result: {delete_result}")

    search_result_after = controller.search(
        portfolio=portfolio,
        org=org,
        query=unique_token,
        datatypes=[ring],
        limit=10,
        offset=0,
    )
    after_total = int(search_result_after.get("total", 0))
    print(f"✅ Search-after-delete total: {after_total}")

    passed = before_total > 0 and after_total == 0
    return {
        "success": passed,
        "table": search_table_name,
        "doc_id": doc_id,
        "token": unique_token,
        "index_result": index_result,
        "search_before_total": before_total,
        "delete_result": delete_result,
        "search_after_total": after_total,
    }


def main():
    parser = argparse.ArgumentParser(description="Run smoke test for Renglo Search Engine V1.")
    parser.add_argument("environment_name", type=str, help="Environment name prefix (e.g. dev, prod, test).")

    available_profiles = get_available_aws_profiles()
    parser.add_argument(
        "--aws-profile",
        type=str,
        choices=available_profiles,
        default="default",
        help=f"Specify AWS profile (Available: {', '.join(available_profiles)})",
    )
    parser.add_argument(
        "--region",
        type=str,
        default="us-east-1",
        help="AWS region (default: us-east-1)",
    )
    parser.add_argument("--portfolio", type=str, default="test_portfolio", help="Portfolio id for test data")
    parser.add_argument("--org", type=str, default="test_org", help="Org id for test data")
    parser.add_argument("--ring", type=str, default="test_ring", help="Ring id for test data")

    args = parser.parse_args()
    result = run(
        env_name=args.environment_name,
        aws_profile=args.aws_profile,
        region=args.region,
        portfolio=args.portfolio,
        org=args.org,
        ring=args.ring,
    )

    print("\n📊 Search Engine V1 Smoke Test Summary")
    print(f"Table: {result['table']}")
    print(f"Doc  : {result['doc_id']}")
    print(f"Token: {result['token']}")
    print(f"Hits before delete: {result['search_before_total']}")
    print(f"Hits after delete : {result['search_after_total']}")

    if result["success"]:
        print("\n✅ PASS: index/search/delete lifecycle works.")
        raise SystemExit(0)

    print("\n❌ FAIL: lifecycle validation failed.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()

