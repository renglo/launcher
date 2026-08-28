"""GitHub Actions OIDC subject (sub) helpers for IAM trust policies.

GitHub's default sub used to be ``repo:OWNER/REPO:environment:STAGE``.
Repos created or renamed after 15 Jul 2026 (and any repo that opted in) use an
immutable prefix: ``repo:OWNER@OWNER-ID/REPO@REPO-ID:environment:STAGE``.

``github_repo`` stays ``OWNER/REPO`` (SSM ``GITHUB_REPOSITORY``). The IAM
trust policy uses ``github_oidc_sub_prefix`` when set — copy it from the GitHub
repo Settings → Actions → OIDC page.
"""

from __future__ import annotations

_CLAIM_SEPARATORS = (
    ":environment:",
    ":ref:",
    ":pull_request",
    ":job_workflow_ref:",
)


def normalize_github_oidc_repo(value: str) -> str:
    """Return the repo segment of a GitHub OIDC ``sub`` (no leading ``repo:``).

    Accepts ``OWNER/REPO``, the immutable ``OWNER@ID/REPO@ID``, or a paste from
    the GitHub UI including the ``repo:`` prefix and/or ``:environment:…``.
    """
    v = (value or "").strip()
    if v.startswith("repo:"):
        v = v[5:]
    for sep in _CLAIM_SEPARATORS:
        idx = v.find(sep)
        if idx != -1:
            v = v[:idx]
            break
    return v.strip().rstrip(":")


def resolve_github_oidc_repo(*, github_repo: str, oidc_sub_prefix: str = "") -> str:
    return normalize_github_oidc_repo(oidc_sub_prefix or github_repo)


def resolve_github_handlers_oidc_repo(
    *,
    github_repo: str,
    github_handlers_repo: str,
    github_oidc_sub_prefix: str = "",
    github_handlers_oidc_sub_prefix: str = "",
) -> str:
    """OIDC repo segment for handlers roles.

    Same BOM repo → inherit the backend prefix. A distinct handlers repo uses
    its own prefix, or ``github_handlers_repo`` when that is omitted.
    """
    handlers = (github_handlers_repo or github_repo).strip() or github_repo
    explicit = (github_handlers_oidc_sub_prefix or "").strip()
    if explicit:
        return normalize_github_oidc_repo(explicit)
    if handlers == github_repo:
        return resolve_github_oidc_repo(
            github_repo=github_repo,
            oidc_sub_prefix=github_oidc_sub_prefix,
        )
    return normalize_github_oidc_repo(handlers)
