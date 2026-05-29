"""
Create OpenSearch index for an environment.
All names derived from env_name: domain {env}-search, collection {env}-collection, index {env}-documents.
If neither exists, creates OpenSearch Serverless collection with required policies.
Idempotent: skips creation if index/collection already exists.
Returns endpoint URL and index name for config (OPENSEARCH_ENDPOINT, OPENSEARCH_INDEX).
"""

import argparse
import json
import time
from typing import Dict, Optional

import boto3


def _parse_endpoint(endpoint: str) -> tuple[str, int]:
    """Parse OpenSearch endpoint URL to host and port."""
    endpoint = endpoint.strip().lower()
    if endpoint.startswith("https://"):
        endpoint = endpoint[8:]
    elif endpoint.startswith("http://"):
        endpoint = endpoint[7:]
    if "/" in endpoint:
        endpoint = endpoint.split("/")[0]
    if ":" in endpoint:
        host, port_str = endpoint.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            port = 443
    else:
        host = endpoint
        port = 443
    return host, port


def _get_domain_endpoint(
    domain_name: str, aws_region: str, aws_profile: str
) -> Optional[str]:
    """Get OpenSearch domain endpoint via boto3."""
    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    client = session.client("opensearch")
    try:
        response = client.describe_domain(DomainName=domain_name)
        domain = response["DomainStatus"]
        if domain.get("Processing"):
            raise ValueError(
                f"Domain '{domain_name}' is still processing. Wait for it to become active."
            )
        endpoint = (
            domain.get("Endpoint")
            or domain.get("Endpoints", {}).get(aws_region)
            or domain.get("EndpointV2")
        )
        if endpoint:
            if not endpoint.startswith("http"):
                endpoint = f"https://{endpoint}"
            return endpoint
        return None
    except client.exceptions.ResourceNotFoundException:
        return None
    except Exception as e:
        print(f"❌ Failed to get domain endpoint: {e}")
        raise


def _get_serverless_endpoint(
    collection_name: str, aws_region: str, aws_profile: str
) -> Optional[str]:
    """Get OpenSearch Serverless collection endpoint via boto3."""
    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    client = session.client("opensearchserverless")
    try:
        response = client.batch_get_collection(names=[collection_name])
        details = response.get("collectionDetails", [])
        if not details:
            return None
        status = details[0].get("status")
        if status != "ACTIVE":
            return None
        return details[0].get("collectionEndpoint")
    except Exception as e:
        print(f"❌ Failed to get Serverless endpoint: {e}")
        raise


def _ensure_aoss_iam_permission(
    env_name: str, aws_region: str, aws_profile: str
) -> None:
    """Ensure the tt_policy has aoss:APIAccessAll. Add it if missing. Idempotent."""
    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    iam = session.client("iam")
    sts = session.client("sts")
    account_id = sts.get_caller_identity()["Account"]
    policy_name = f"{env_name}_tt_policy"
    policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"

    try:
        iam.get_policy(PolicyArn=policy_arn)
    except iam.exceptions.NoSuchEntityException:
        print(f"  ⚠️  IAM policy '{policy_name}' not found. Run deploy_environment first.")
        return

    policy_versions = iam.list_policy_versions(PolicyArn=policy_arn)
    current = next((v for v in policy_versions["Versions"] if v["IsDefaultVersion"]), None)
    if not current:
        return

    current_doc = iam.get_policy_version(
        PolicyArn=policy_arn, VersionId=current["VersionId"]
    )["PolicyVersion"]["Document"]

    has_aoss = any(
        stmt.get("Action") == "aoss:APIAccessAll"
        or (
            isinstance(stmt.get("Action"), list)
            and "aoss:APIAccessAll" in stmt["Action"]
        )
        for stmt in current_doc.get("Statement", [])
    )
    if has_aoss:
        print(f"  ✅ IAM policy already has aoss:APIAccessAll")
        return

    aoss_statement = {
        "Effect": "Allow",
        "Action": "aoss:APIAccessAll",
        "Resource": "*",
    }
    new_statements = current_doc.get("Statement", []) + [aoss_statement]
    new_doc = {**current_doc, "Statement": new_statements}

    try:
        iam.create_policy_version(
            PolicyArn=policy_arn,
            PolicyDocument=json.dumps(new_doc),
            SetAsDefault=True,
        )
    except iam.exceptions.LimitExceededException:
        non_default = [v for v in policy_versions["Versions"] if not v["IsDefaultVersion"]]
        non_default.sort(key=lambda v: v["CreateDate"])
        if not non_default:
            raise RuntimeError(
                f"Policy '{policy_name}' has 5 versions and cannot delete default. "
                "Delete old versions manually in IAM console."
            )
        iam.delete_policy_version(PolicyArn=policy_arn, VersionId=non_default[0]["VersionId"])
        print(f"  🗑️  Deleted oldest policy version to make room")
        iam.create_policy_version(
            PolicyArn=policy_arn,
            PolicyDocument=json.dumps(new_doc),
            SetAsDefault=True,
        )
    print(f"  ✅ Added aoss:APIAccessAll to IAM policy '{policy_name}'")


def _get_caller_arn(aws_region: str, aws_profile: str) -> str:
    """Get ARN of the current caller (user or role) for data access policy."""
    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    sts = session.client("sts")
    identity = sts.get_caller_identity()
    return identity["Arn"]


def _create_serverless_collection(
    env_name: str,
    aws_region: str,
    aws_profile: str,
    lambda_role_arn: Optional[str] = None,
) -> str:
    """Create OpenSearch Serverless collection with encryption, network, and data access policies."""
    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    client = session.client("opensearchserverless")
    sts = session.client("sts")
    account_id = sts.get_caller_identity()["Account"]
    caller_arn = _get_caller_arn(aws_region, aws_profile)

    collection_name = f"{env_name}-collection"
    policy_prefix = f"{env_name}-"
    collection_pattern = f"collection/{collection_name}"
    index_pattern = f"index/{collection_name}/*"

    def _create_encryption_policy():
        policy_name = f"{policy_prefix}encryption"
        try:
            client.create_security_policy(
                name=policy_name,
                type="encryption",
                policy=json.dumps(
                    {
                        "Rules": [
                            {
                                "ResourceType": "collection",
                                "Resource": [collection_pattern],
                            }
                        ],
                        "AWSOwnedKey": True,
                    }
                ),
                description=f"Encryption for {collection_name}",
            )
            print(f"  ✅ Encryption policy '{policy_name}' created")
        except client.exceptions.ConflictException:
            print(f"  ✅ Encryption policy '{policy_name}' already exists")

    def _create_network_policy():
        policy_name = f"{policy_prefix}network"
        try:
            client.create_security_policy(
                name=policy_name,
                type="network",
                policy=json.dumps(
                    [
                        {
                            "Description": f"Network access for {collection_name}",
                            "Rules": [
                                {"ResourceType": "collection", "Resource": [collection_pattern]},
                                {"ResourceType": "dashboard", "Resource": [collection_pattern]},
                            ],
                            "AllowFromPublic": True,
                        }
                    ]
                ),
                description=f"Network for {collection_name}",
            )
            print(f"  ✅ Network policy '{policy_name}' created")
        except client.exceptions.ConflictException:
            print(f"  ✅ Network policy '{policy_name}' already exists")

    def _create_data_access_policy():
        policy_name = f"{policy_prefix}data"
        principals = [caller_arn, f"arn:aws:iam::{account_id}:root"]
        if lambda_role_arn:
            principals.append(lambda_role_arn)
        policy_doc = [
            {
                "Rules": [
                    {
                        "ResourceType": "index",
                        "Resource": [index_pattern],
                        "Permission": [
                            "aoss:CreateIndex",
                            "aoss:DeleteIndex",
                            "aoss:UpdateIndex",
                            "aoss:DescribeIndex",
                            "aoss:ReadDocument",
                            "aoss:WriteDocument",
                        ],
                    },
                    {
                        "ResourceType": "collection",
                        "Resource": [collection_pattern],
                        "Permission": ["aoss:CreateCollectionItems"],
                    },
                ],
                "Principal": principals,
            }
        ]
        try:
            client.create_access_policy(
                name=policy_name,
                type="data",
                policy=json.dumps(policy_doc),
                description=f"Data access for {collection_name}",
            )
            print(f"  ✅ Data access policy '{policy_name}' created")
        except client.exceptions.ConflictException:
            print(f"  ✅ Data access policy '{policy_name}' already exists")

    def _create_collection():
        try:
            client.create_collection(
                name=collection_name,
                type="SEARCH",
                description=f"Search collection for {env_name}",
            )
            print(f"  ✅ Collection '{collection_name}' created")
        except client.exceptions.ConflictException:
            print(f"  ✅ Collection '{collection_name}' already exists")

    print(f"🔧 Creating OpenSearch Serverless collection '{collection_name}'...")
    _create_encryption_policy()
    _create_network_policy()
    _create_data_access_policy()
    _create_collection()

    print(f"  ⏳ Waiting for collection to become active (up to ~10 min)...")
    for _ in range(60):
        response = client.batch_get_collection(names=[collection_name])
        details = response.get("collectionDetails", [])
        if details:
            status = details[0].get("status")
            if status == "ACTIVE":
                endpoint = details[0].get("collectionEndpoint")
                if endpoint:
                    print(f"  ✅ Collection is active")
                    print(f"  ⏳ Waiting 45s for data access rules to propagate...")
                    time.sleep(45)
                    return endpoint
            elif status == "FAILED":
                raise RuntimeError(f"Collection '{collection_name}' failed to create")
        time.sleep(10)

    raise RuntimeError(f"Collection '{collection_name}' did not become active in time")


def _create_opensearch_client(
    endpoint: str, aws_region: str, aws_profile: str, is_serverless: bool = False
):
    """Create OpenSearch client with AWS SigV4 auth. Use service='aoss' for Serverless."""
    try:
        from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
    except ImportError:
        raise ImportError(
            "opensearch-py is required. Install with: pip install opensearch-py"
        )

    host, port = _parse_endpoint(endpoint)
    session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
    credentials = session.get_credentials()
    service = "aoss" if is_serverless else "es"
    auth = AWSV4SignerAuth(credentials, aws_region, service)

    return OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )


INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "org": {"type": "keyword"},
            "datatype": {"type": "keyword"},
            "portfolio": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "doc_index": {"type": "keyword"},
            "added": {"type": "date"},
            "modified": {"type": "date"},
            "attributes": {"type": "object", "dynamic": True},
            "_search_text": {"type": "text"},
        }
    }
}


def create_opensearch_index(
    env_name: str,
    aws_region: str,
    aws_profile: str,
    lambda_role_arn: Optional[str] = None,
) -> Dict[str, str]:
    """
    Create OpenSearch index for environment. Idempotent.
    Domain/collection names derived from env_name: {env}-search (provisioned) or {env}-collection (Serverless).
    Returns endpoint URL and index name for config.
    """
    index_name = f"{env_name}-documents"
    domain_name = f"{env_name}-search"
    collection_name = f"{env_name}-collection"

    if lambda_role_arn is None:
        session = boto3.Session(profile_name=aws_profile, region_name=aws_region)
        account_id = session.client("sts").get_caller_identity()["Account"]
        lambda_role_arn = f"arn:aws:iam::{account_id}:role/{env_name}_tt_role"

    print("🔧 Ensuring IAM policy has OpenSearch Serverless permission...")
    _ensure_aoss_iam_permission(env_name, aws_region, aws_profile)

    endpoint = _get_domain_endpoint(domain_name, aws_region, aws_profile)
    is_serverless = False
    if endpoint:
        pass
    else:
        endpoint = _get_serverless_endpoint(collection_name, aws_region, aws_profile)
        if endpoint:
            is_serverless = True
        else:
            endpoint = _create_serverless_collection(
                env_name, aws_region, aws_profile, lambda_role_arn=lambda_role_arn
            )
            is_serverless = True

    client = _create_opensearch_client(
        endpoint, aws_region, aws_profile, is_serverless=is_serverless
    )

    try:
        if client.indices.exists(index=index_name):
            print(f"✅ Index '{index_name}' already exists. Skipping creation.")
        else:
            client.indices.create(index=index_name, body=INDEX_MAPPING)
            print(f"✅ Index '{index_name}' created successfully.")
    except Exception as e:
        print(f"❌ Failed to create index: {e}")
        raise

    return {
        "opensearch_endpoint": endpoint,
        "opensearch_index": index_name,
    }


def run(
    env_name: str,
    aws_profile: str,
    aws_region: str,
    lambda_role_arn: Optional[str] = None,
) -> Dict[str, str]:
    """Programmatic entry point that returns structured data."""
    return create_opensearch_index(
        env_name=env_name,
        aws_region=aws_region,
        aws_profile=aws_profile,
        lambda_role_arn=lambda_role_arn,
    )


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Create OpenSearch index for an environment. "
        "Looks up domain {env}-search or collection {env}-collection. Returns endpoint and index for config."
    )
    parser.add_argument(
        "environment_name",
        type=str,
        help="Environment name (e.g., dev, prod, noma). Uses domain '{env}-search' or collection '{env}-collection'.",
    )
    parser.add_argument(
        "--aws-profile",
        type=str,
        required=True,
        help="AWS profile to use (required)",
    )
    parser.add_argument(
        "--aws-region",
        type=str,
        default="us-east-1",
        help="AWS region (default: us-east-1)",
    )

    args = parser.parse_args()

    result = run(
        env_name=args.environment_name,
        aws_profile=args.aws_profile,
        aws_region=args.aws_region,
    )

    print("\n🎯 Add to config (env_config.py or environment variables):\n")
    print(f"OPENSEARCH_ENDPOINT = '{result['opensearch_endpoint']}'")
    print(f"OPENSEARCH_INDEX = '{result['opensearch_index']}'")


if __name__ == "__main__":
    main()
