"""Unit tests for CodeArtifact owner resolution (no CDK import)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_LIB = Path(__file__).resolve().parents[1] / "cdk"
sys.path.insert(0, str(_LIB))

from lib.package_registry import codeartifact_owners, validate_package_registry  # noqa: E402


def test_owners_tenant_only_when_omitted() -> None:
    assert codeartifact_owners("111122223333") == ["111122223333"]
    assert codeartifact_owners("111122223333", None) == ["111122223333"]


def test_owners_empty_domain_owners() -> None:
    assert codeartifact_owners("111122223333", {"domain_owners": []}) == ["111122223333"]


def test_owners_multiple_foreign() -> None:
    assert codeartifact_owners(
        "111122223333",
        {"domain_owners": ["444455556666", "777788889999", "444455556666"]},
    ) == ["111122223333", "444455556666", "777788889999"]


def test_rejects_legacy_domain_owner() -> None:
    with pytest.raises(ValueError, match="domain_owners"):
        codeartifact_owners("111122223333", {"domain_owner": "444455556666"})


def test_rejects_non_list_domain_owners() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        codeartifact_owners("111122223333", {"domain_owners": "444455556666"})


def test_rejects_empty_entry() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        codeartifact_owners("111122223333", {"domain_owners": [""]})


def test_validate_package_registry() -> None:
    assert validate_package_registry(None) is None
    cfg = {"domain_owners": ["444455556666"]}
    assert validate_package_registry(cfg) is cfg
    with pytest.raises(ValueError, match="object"):
        validate_package_registry("nope")
