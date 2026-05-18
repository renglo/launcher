README

If you want to install a new Renglo Environment use this:

[ENVIRONMENT_README.md](ENVIRONMENT_README.md)

IAM policy helpers (`generate_env_deployment_tt_policy`, `provision_env_deployment_tt_identity`) and GitHub env injection (`inject_github_env_vars`) live under **`../bootstrap/helpers/`** — see [bootstrap/README.md](../bootstrap/README.md).

## Deploy

From `launcher/scripts/`:

```bash
python deploy_environment.py <environment_name> --aws-profile <profile> --aws-region <region> --github-repo <org/repo>
```

CDK bootstrap is optional in the current SDK-based flow.
Use `--enable-cdk-bootstrap` only if you want to prepare the account for CDK deploy workflows.
The long-term intention is to migrate backend provisioning fully to CDK.

For first-time backend Lambda creation, the launcher automatically builds and pushes a minimal seed image from `scripts/backend/seed-image/`.
The launcher provisions backend resources for both `production` and `staging`, and configures one Lambda alias per stage.
It also provisions CodeDeploy (Lambda compute platform): `production` uses `CodeDeployDefault.LambdaCanary10Percent10Minutes` and `staging` uses `CodeDeployDefault.LambdaAllAtOnce`.
`--seed-image-uri` is optional and only needed to override that default seed image.

After deploy, resource ARNs and names are written to **`launcher/state/<environment_name>/created_resources.json`** (single source of truth for teardown).

## Tear down

To **delete** everything that `deploy_environment.py` created for an environment (reads `launcher/state/<env>/created_resources.json`):

```bash
cd scripts
python teardown_environment.py <environment_name> --aws-profile <profile> --aws-region <region> --yes
```

Options:

- **`--skip-tables`** — keep DynamoDB tables and data
- **`--skip-cognito`** — keep the Cognito user pool
- **`--keep-logs`** — do not delete `/aws/lambda/<backend-function>` CloudWatch log groups
- Without **`--yes`**, you must type the environment name to confirm

The script removes GitHub Actions deploy IAM roles/policies from the manifest, then deletes CodeDeploy, Lambdas, API Gateways, WebSocket APIs, ECR repo, tenant IAM role/policy, S3 (only if `s3.created` is true in JSON), Cognito, DynamoDB tables, and finally **`launcher/state/<env>/`** locally.

The account-level GitHub OIDC provider (`token.actions.githubusercontent.com`) is **not** deleted (it is often shared across environments).
