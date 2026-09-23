# Launcher — CDK infrastructure

Scripts and utilities for provisioning and managing Renglo cloud environments. Defines the tenant platform as **CloudFormation** via CDK (`launcher/cdk/`). The orchestrator lives in [bootstrap/README.md](../bootstrap/README.md).

---

## Stacks

Two CloudFormation stacks per environment (synth output in `bootstrap/output/<env>/`):

| Stack | CF name | Description | Contents |
|-------|---------|-------------|----------|
| A | `<env>-stack-a` | Reglo deployment -— auth, storage, runtime | Cognito, S3/DynamoDB, SES (team invite email), backend ECR, seed CodeBuild, tenant IAM, CodeDeploy, releases OIDC |
| B | `<env>-stack-b` | Reglo deployment — app, extension | Backend Lambdas (seed), REST + WebSocket API Gateway, optional extension. Handler compute is on peer stacks. |

**Deploy order:** `<env>-stack-a` (builds seed image automatically) → `<env>-stack-b`

Resource names inside the stacks still use `env_name` from `customer-config.json` (e.g. `{env}_backend` ECR repo).

---

## Configuration

```bash
cd launcher/cdk
cp customer-config.example.json customer-config.json
```

| Field | Description |
|-------|-------------|
| `env_name` | Resource prefix and synth output folder name |
| `github_repo` | BOM repo (`OWNER/REPO`) — SSM `GITHUB_REPOSITORY`, not the IAM `sub` |
| `github_owner_id` / `github_repo_id` | Optional. GitHub owner/repo IDs for immutable OIDC `sub` claims. Omit if unknown. |
| `enable_staging` | `true` → staging Lambda + APIs + staging OIDC |
| `email_from` | **Required** — SES from-address for team invite email (app-owned address or domain) |
| `email_identity_type` | **Required** — `email` (inbox verify) or `domain` (domain verify; preferred for no-reply) |
| `email_hosted_zone_id` | Route53 public hosted zone ID when DNS for that domain is in this account (pattern A); omit for external DNS |

**Team invite email is required.** Cognito self-signup is disabled — invites are how users join after the first admin. Configure email in bootstrap [§3.3](../bootstrap/README.md#step-33--set-up-application-email-required), then [§7 Path B](../bootstrap/README.md#path-b--local-development-default--no-cicd) for local testing (no CI/CD).

Account and region are **not** in `customer-config.json`. Templates are environment-agnostic (`AWS::AccountId` / `AWS::Region`); choose the target account and region at deploy time (AWS profile / CLI region).

Platform-wide defaults (`architecture`, backend seed image URI/tag, Cognito token lifetime): `launcher/cdk/platform_defaults.json`. Set `cognito.token_validity_hours` (1–24, default **24**) for access/ID token lifetime on the app client — the console session follows the ID token `exp`.

---

## Synth and deploy

```bash
cd <infra-installer>
bash bootstrap/setup-venvs.sh
python bootstrap/install.py synth
```

Deploy with **CloudFormation CLI** from `bootstrap/output/<env>/`, or with **CDK CLI** from `bootstrap/output/<env>/cdk/`. Full CF script: [bootstrap/README.md appendix](../bootstrap/README.md#appendix-cloudformation-deploy-full-script).

```bash
export ENV=<env>
export AWS_PROFILE=<aws-profile>
export AWS_REGION=<aws-region>

# CloudFormation (from env root) — stack-a builds the seed image automatically
cd bootstrap/output/$ENV
aws cloudformation deploy --template-file "$ENV-stack-a.template.json" --stack-name "$ENV-stack-a" --capabilities CAPABILITY_NAMED_IAM --profile "$AWS_PROFILE"
aws cloudformation deploy --template-file "$ENV-stack-b.template.json" --stack-name "$ENV-stack-b" --capabilities CAPABILITY_NAMED_IAM --profile "$AWS_PROFILE"

# CDK (from cdk/)
cd bootstrap/output/$ENV/cdk
cdk deploy "$ENV-stack-a" --app "python app.py" --output . --require-approval never --profile "$AWS_PROFILE"
cdk deploy "$ENV-stack-b" --app "python app.py" --output . --exclusively --require-approval never --profile "$AWS_PROFILE"
```

**Important:** `<env>-stack-b` requires the seed image in ECR (`<env>_backend:seed`). Stack-a builds and pushes it automatically via a CodeBuild custom resource during its own deploy; the stack-a deploy does not complete until the build succeeds. To rebuild manually: `aws codebuild start-build --project-name "$ENV-seed-image"`.

**Re-deploying `<env>-stack-b`:** resets Lambda code to the seed image. Re-run the releases pipeline afterward.

Handler compute (Lambda / Fargate / EC2) is on `{env}-peer-*` stacks. See [bom-helper/docs/PEERS.md](../bom-helper/docs/PEERS.md).

---

## Post-deploy

Stack-b writes bootstrap SSM parameters when deployed via CDK. CloudFormation-only deploys still need `write-state` (bootstrap §6).

**Infrastructure deploy is not the end of installation.** Follow **[bootstrap §7](../bootstrap/README.md#7-after-bootstrap--make-the-app-usable)** — default **Path B** (local API, no GitHub). Operators generate `bootstrap/output/<env>/local-dev/` with `write-local-config` ([Step 7.5](../bootstrap/README.md#step-75--generate-local-developer-config-bundle)). Cloud production and CI/CD are optional later ([Path A](../bootstrap/README.md#path-a--cloud-go-live-optional-later) + [§8](../bootstrap/README.md#8-cicd-contract-optional--cloud-production-only)).

SSM paths (bootstrap [§6](../bootstrap/README.md#6-bootstrap-config-in-ssm-write-state-after-stack-b)):

- `/{env}/bootstrap/platform-vars/production`
- `/{env}/bootstrap/platform-vars/staging`
- `/{env}/bootstrap/deploy-input`
- `/{env}/bootstrap/peer-routes` (after peer stacks exist)

CI workflows (only when you choose cloud go-live) read these via OIDC (bootstrap [§8](../bootstrap/README.md#8-cicd-contract-optional--cloud-production-only)).

---

## GitHub OIDC provider (`CreateGitHubOIDC`)

`<env>-stack-a` exposes a CloudFormation parameter **`CreateGitHubOIDC`** (default `false`). Set it to `true` on the first deploy in an account that does not yet have the GitHub Actions OIDC provider (`token.actions.githubusercontent.com`). If the provider already exists, leave the default.

```bash
cd bootstrap/output/$ENV/cdk
cdk deploy "$ENV-stack-a" --app "python app.py" --output . \
  --parameters CreateGitHubOIDC=true \
  --profile "$AWS_PROFILE"
```

---

## Legacy flow (boto3)

For the legacy boto3 deployment path, see [ENVIRONMENT_README.md](ENVIRONMENT_README.md).

---

## Tear down

**CloudFormation:**

```bash
aws cloudformation delete-stack --stack-name "${ENV}-stack-b" --profile "$AWS_PROFILE" --region "$AWS_REGION"
aws cloudformation wait stack-delete-complete --stack-name "${ENV}-stack-b" --profile "$AWS_PROFILE" --region "$AWS_REGION"
aws cloudformation delete-stack --stack-name "${ENV}-stack-a" --profile "$AWS_PROFILE" --region "$AWS_REGION"
```

**CDK:**

```bash
cd bootstrap/output/$ENV/cdk
cdk destroy "$ENV-stack-b" "$ENV-stack-a" --app "python app.py" --output . --profile "$AWS_PROFILE"
```

The account-level OIDC provider is **not** deleted (shared across environments).

---

## License

This project is licensed under the MIT License. See [LICENSE.txt](LICENSE.txt) for details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines and the Contributor License Agreement.
