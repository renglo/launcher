# Launcher — core backend environment

Provisions tenant AWS resources (DynamoDB, Cognito, IAM, S3, backend Lambda container + ECR, API Gateway, WebSocket, CodeDeploy, GitHub OIDC) and writes local state under `launcher/state/<environment_name>/`.

**Full walkthrough (venv, deploy, outputs, application wiring):** [ENVIRONMENT_README.md](ENVIRONMENT_README.md)

---

## New environment (recommended)

On **`<main-launcher-root>`** (folder with `bootstrap/`, `launcher/`, `extensions-service/` siblings), use the bootstrap orchestrator — it runs launcher deploy + extensions provision and merges state:

```bash
bash bootstrap/setup-venvs.sh

python bootstrap/install.py <extension> \
  --profile <aws-profile> \
  --aws-region us-east-1 \
  --github-repo <org>/<releases-repo>
```

See [bootstrap/README.md](../bootstrap/README.md) and [bootstrap/ARCHITECTURE.md](../bootstrap/ARCHITECTURE.md).

IAM policy helpers (`generate_env_deployment_tt_policy`, `provision_env_deployment_tt_identity`) and GitHub env injection (`inject_github_env_vars`) live under **`../bootstrap/helpers/`**.

---

## Launcher only (standalone deploy)

From **`<main-launcher-root>/launcher`**:

```bash
python3.12 -m venv launch-venv
# Linux/macOS/WSL: source launch-venv/bin/activate
# Windows: launch-venv\Scripts\activate
pip install -r requirements.txt

cd scripts
python deploy_environment.py <environment_name> \
  --aws-profile <profile> \
  --aws-region <region> \
  --github-repo <org>/<releases-repo>
```

`--github-repo` is **required** (GitHub OIDC trust for the releases / control repo).

**Optional flags:** `--disable-staging-role`, `--enable-cdk-bootstrap`, `--seed-image-uri <uri>`, `--dry-run`

- CDK bootstrap is **off** by default (SDK-based provisioning today). Use `--enable-cdk-bootstrap` only to prepare the account for future CDK workflows.
- First-time backend Lambda: a minimal seed image is built/pushed from `scripts/backend/seed-image/` unless you pass `--seed-image-uri`.
- Backend is provisioned for **`production`** and **`staging`** (Lambda alias per stage). CodeDeploy: production = `LambdaCanary10Percent10Minutes`, staging = `LambdaAllAtOnce`.

---

## State files (`launcher/state/<environment_name>/`)

| File | Role |
|------|------|
| `created_resources.json` | Single source of truth for **teardown** (AWS ARNs and names) |
| `env_config.py` | Generated Python config for the **system** app (copy into product repo if needed) |
| `production.json` | GitHub Environment payload (`VARS` / `SECRETS`) for production |
| `staging.json` | Same for staging (unless `--disable-staging-role`) |

After bootstrap, merged release payloads also live under `bootstrap/state/<extension>/platform_vars.production.json` (and staging). Sync to GitHub:

```bash
python bootstrap/helpers/inject_github_env_vars.py \
  --json bootstrap/state/<extension>/platform_vars.production.json
```

Requires authenticated GitHub CLI (`gh auth login`). See [bootstrap/README.md — Sync GitHub environment variables](../bootstrap/README.md#sync-github-environment-variables).

---

## Tear down

Reads `launcher/state/<env>/created_resources.json`:

```bash
cd launcher/scripts
python teardown_environment.py <environment_name> \
  --aws-profile <profile> \
  --aws-region <region> \
  --yes
```

| Flag | Effect |
|------|--------|
| `--skip-tables` | Keep DynamoDB tables and data |
| `--skip-cognito` | Keep Cognito user pool |
| `--keep-logs` | Keep `/aws/lambda/<backend-function>` CloudWatch log groups |
| (no `--yes`) | Must type environment name to confirm |

Removes GitHub deploy IAM roles/policies from the manifest, then CodeDeploy, Lambdas, API Gateways, WebSocket APIs, ECR, tenant IAM role/policy, S3 (if created), Cognito, DynamoDB tables, and local **`launcher/state/<env>/`**.

The account-level GitHub OIDC provider (`token.actions.githubusercontent.com`) is **not** deleted (often shared across environments).

Full-platform teardown (launcher + extensions + bootstrap state): `python bootstrap/uninstall.py <extension> --profile <profile> --yes`
