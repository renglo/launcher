# Setting up a Renglo cloud environment (launcher)

Step-by-step guide for **`deploy_environment.py`**. For launcher + handlers + merged bootstrap state, prefer [bootstrap/README.md](../bootstrap/README.md) on **`<main-launcher-root>`** (`bootstrap/`, `launcher/`, `extensions-service/` siblings).

Short index: [README.md](README.md)

---

## Prerequisites

- Python **3.12**, AWS CLI
- Named AWS profile with permissions to provision the environment
- Optional: minimal operator policy —  
  `python bootstrap/helpers/generate_env_deployment_tt_policy.py <env> --aws-profile <profile>`

---

## 1. Virtual environment

From **`<main-launcher-root>/launcher`**:

```bash
python3.12 -m venv launch-venv
source launch-venv/bin/activate   # Windows: launch-venv\Scripts\activate
pip install -r requirements.txt
```

Or create all venvs at once: `bash bootstrap/setup-venvs.sh` from `<main-launcher-root>`.

`opensearch-py` is only needed for the OpenSearch index step; `boto3` is always required.

---

## 2. AWS profile

```bash
aws configure list-profiles
```

Use the profile that points at the target AWS account.

---

## 3. Deploy environment

Creates DynamoDB tables, Cognito user pool, tenant IAM policy/role, S3 bucket, GitHub OIDC deploy roles, and backend infra per stage (**production** + **staging**): ECR, container Lambda, alias, REST API Gateway stage, WebSocket API, CodeDeploy deployment group.

```bash
cd scripts
python deploy_environment.py <environment_name> \
  --aws-region <aws_region> \
  --aws-profile <aws_profile> \
  --github-repo <org>/<releases-repo>
```

| Flag | Purpose |
|------|---------|
| `--disable-staging-role` | Do not create staging GitHub OIDC role / skip staging-oriented outputs where applicable |
| `--enable-cdk-bootstrap` | Run CDK bootstrap (optional; default flow uses SDK scripts) |
| `--dry-run` | Plan IAM/backend changes without creating resources |

**CDK:** Bootstrap is skipped by default. `--enable-cdk-bootstrap` is for forward compatibility if deploy moves fully to CDK.

**Seed image:** Use the CDK bootstrap flow ([bootstrap/README.md](../bootstrap/README.md)): stack-a creates a CodeBuild project that builds and pushes `<env>_backend:seed`. No local Docker.

**CodeDeploy:** `production` → `CodeDeployDefault.LambdaCanary10Percent10Minutes`; `staging` → `CodeDeployDefault.LambdaAllAtOnce`.

---

## 4. Deploy outputs (`launcher/state/<environment_name>/`)

Written automatically — no need to hand-edit tables/Cognito/WebSocket IDs for infra:

| Output | Use |
|--------|-----|
| `created_resources.json` | Teardown (`teardown_environment.py`) |
| `env_config.py` | Copy into product **`system`** tree (see §5) |
| `production.json` | GitHub Environment **production** (`VARS` / `SECRETS`) |
| `staging.json` | GitHub Environment **staging** |

Terminal summary lists ARNs, bucket name, Cognito IDs, WebSocket URLs, OpenSearch endpoint (if created), and paths to these files.

**OpenSearch:** Index creation runs during deploy. Uses provisioned domain `{env}-search` if it exists, otherwise OpenSearch Serverless collection `{env}-collection`. Standalone retry:

```bash
cd scripts
python create_opensearch_index.py <environment_name> \
  --aws-profile <aws_profile> --aws-region <region>
```

**GitHub Environments (releases repo):** After bootstrap merge, push vars/secrets:

```bash
python bootstrap/helpers/inject_github_env_vars.py \
  --json bootstrap/state/<extension>/platform_vars.production.json
```

Or inject directly from launcher state:

```bash
python bootstrap/helpers/inject_github_env_vars.py \
  --json launcher/state/<environment_name>/production.json
```

Requires `gh auth login`.

---

## 5. Wire the application repos

Infra deploy does **not** deploy the `system` / `console` application code. It generates config you copy or sync.

### `env_config.py`

Deploy writes **`launcher/state/<environment_name>/env_config.py`** with DynamoDB table names, Cognito, S3, WebSocket URLs (production + staging), OpenSearch, etc.

Copy or merge into your product repo’s **`system/env_config.py`** (or equivalent). Set **`CSRF_SESSION_KEY`** and **`SECRET_KEY`** to new random values if not already set in your process.

Example keys (values come from deploy output):

```python
DYNAMODB_ENTITY_TABLE = '<name>_entities'
COGNITO_REGION = 'us-east-1'
COGNITO_USERPOOL_ID = '...'
COGNITO_APP_CLIENT_ID = '...'
S3_BUCKET_NAME = '...'
WEBSOCKET_CONNECTIONS = 'https://<id>.execute-api.<region>.amazonaws.com/production/'
VITE_WEBSOCKET_URL = 'wss://<id>.execute-api.<region>.amazonaws.com/production/'
# staging variants: WEBSOCKET_CONNECTIONS_STAGING, VITE_WEBSOCKET_URL_STAGING
```

### Front-end (console)

Infra provisions an **Amplify Hosting** app (`{env_name}-console`) with `production` and `staging` branches. OAuth callback/sign-out URLs on the Cognito app client are set automatically from Amplify `DefaultDomain` (`https://{branch}.{appId}.amplifyapp.com`). Local dev URLs (`http://localhost:5173/`) are included.

After deploy, CI/CD reads `platform_vars.*` from SSM Parameter Store. Key vars:

| Var | Purpose |
|-----|---------|
| `AMPLIFY_APP_ID` | Amplify app ID for CI zip deploy via OIDC |
| `AMPLIFY_CONSOLE_URL` | Hosted console URL for the stage |
| `COGNITO_DOMAIN` | `{env}.auth.{region}.amazoncognito.com` |

In `.env.development.*` / `.env.production.*` under **`console/`**:

```bash
VITE_COGNITO_REGION='...'
VITE_COGNITO_USERPOOL_ID='...'
VITE_COGNITO_APP_CLIENT_ID='...'
VITE_COGNITO_DOMAIN='...'
VITE_AMPLIFY_CONSOLE_URL='...'
```

Use **`VITE_WEBSOCKET_URL`** / staging variants from `env_config.py` or `production.json` `VARS`.

Console frontend is deployed from the **releases** repo (`github_repo`) via GitHub Actions OIDC (`AWS_GITHUB_OIDC_ROLE_ARN` in `SECRETS`), not by Amplify Git integration.

### Local system environment

For local dev setup, follow the product repo: [system README](https://github.com/renglo/system/blob/main/README.md).

### Backend releases (container Lambda)

Application backend is deployed via **ECR image + CodeDeploy** (aliases `production` / `staging`), not Zappa. CI uses GitHub OIDC role ARNs from `production.json` / `staging.json` `SECRETS` (`AWS_GITHUB_OIDC_ROLE_ARN`).

---

## 6. Tear down

```bash
cd scripts
python teardown_environment.py <environment_name> \
  --aws-profile <aws_profile> \
  --aws-region <aws_region> \
  --yes
```

Optional: `--skip-tables`, `--skip-cognito`, `--keep-logs`. Without `--yes`, type the environment name to confirm. Removes **`launcher/state/<environment_name>/`** after success.

Account-level OIDC provider is retained. For full stack (extensions + bootstrap state): `python bootstrap/uninstall.py <extension> --profile <profile> --yes`.

---

## Optional: custom API domain (Route53)

Manual console steps (unchanged pattern):

1. API Gateway → Custom domain names → create `<environment_name>.renglo.com` (ACM cert on subdomain).
2. API mappings → attach deployed REST API + stage.
3. Route53 CNAME: `NAME=<environment_name>` → **API Gateway domain name** (not the raw invoke URL).

If the UI is blank, verify console/tower env files use the new domain; DNS can lag in some browsers.

---

## Optional: WebSocket troubleshooting

`deploy_environment.py` provisions WebSocket APIs per stage. URLs are in deploy summary, `env_config.py`, and `production.json` / `staging.json`.

To recreate or debug manually:

```bash
cd scripts
python create_websocket_api.py <api_name> "chat_message" \
  "<integration_target_url>" <stage> \
  --aws-profile <profile>
```

`integration_target` is typically the REST stage invoke URL + `/_chat/message`.

---

## Legacy: Zappa-based backend (deprecated)

Older environments used **Zappa** to deploy `system` as a zip Lambda. That path is **not** used by the current launcher flow (container image + ECR + CodeDeploy). If you maintain a legacy tenant still on Zappa, keep your existing `zappa_settings.json` and ops runbooks separate from this document.

Do not follow removed references to `../CLOUD_README.md` or manual-only WebSocket setup as the primary path for new environments.
