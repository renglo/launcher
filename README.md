# Launcher — CDK infrastructure



Defines the tenant platform as **CloudFormation** via CDK (`launcher/cdk/`). The orchestrator lives in [bootstrap/README.md](../bootstrap/README.md).



---



## Stacks



Two CloudFormation stacks per environment (synth output in `bootstrap/output/<env>/`):



| Stack | CF name | Description | Contents |
|-------|---------|-------------|----------|
| A | `<env>-stack-a` | Reglo deployment — auth, storage, runtime | Cognito, S3/DynamoDB, backend ECR, tenant IAM, CodeDeploy, releases OIDC |
| B | `<env>-stack-b` | Reglo deployment — app, compute, extension | Backend Lambdas (seed), REST + WebSocket API Gateway, handlers compute, extension |

**Deploy order:** `<env>-stack-a` → **seed image** → `<env>-stack-b`



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

| `aws_account` / `aws_region` | Target account and region |

| `github_repo` | Releases repo (backend OIDC) |

| `github_handlers_repo` | Handlers/extensions repo |

| `enable_staging` | `true` → staging Lambda + APIs + staging OIDC |

| `compute_type` | `lambda_only` \| `fargate` \| `ec2` |

| `ec2_instance_type` | EC2 instance type for handlers ASG (only `ec2`) |

| `ec2_min_instances` / `ec2_desired_instances` / `ec2_max_instances` | ASG size (only `ec2`) |

Platform-wide defaults (`architecture`, backend seed image URI/tag): `launcher/cdk/platform_defaults.json`.



---



## Synth and deploy



```bash

cd <infra-installer>

bash bootstrap/setup-venvs.sh

python bootstrap/install.py synth

```



Deploy from `bootstrap/output/<env>`:



```bash

export ENV=<env>

export AWS_PROFILE=<aws-profile>

export AWS_REGION=<aws-region>



cd bootstrap/output/$ENV



cdk deploy "$ENV-stack-a" \

  --app "python app.py" --output . --require-approval never --profile "$AWS_PROFILE"



python upload_seed_image.py \

  --env-name "$ENV" --aws-profile "$AWS_PROFILE" --aws-region "$AWS_REGION"



# compute_type=ec2 → requires VPC and subnets

cdk deploy "$ENV-stack-b" \

  --app "python app.py" \

  --output . \

  --exclusively \

  --parameters VpcId=<vpc-id> \

  --parameters 'SubnetIds=<subnet-ids>' \

  --require-approval never \

  --profile "$AWS_PROFILE"

```



**Important:** `<env>-stack-b` requires the seed image in ECR (`<env>_backend:seed`) before deploy.



**Re-deploying `<env>-stack-b`:** resets Lambda code to the seed image. Re-run the releases pipeline afterward.



---



## Post-deploy



```bash

cd <infra-installer>

python bootstrap/install.py write-state \

  --env-name <env> \

  --aws-profile <aws-profile> \

  --aws-region <aws-region>

```



State is written to `s3://<env>-<account>-<region>/params/` — see [bootstrap/README.md §8](../bootstrap/README.md#8-sync-github-environment-variables).



---



## OIDC prerequisite (optional)



CDK **references** the GitHub OIDC provider; it does not create it. If the account already has it, skip this. Otherwise:



```bash

python bootstrap/install.py ensure-oidc --aws-profile <aws-profile> --aws-region <aws-region>

```



---



## Legacy flow (boto3)



`scripts/deploy_environment.py` remains available for environments not using CDK. See [ENVIRONMENT_README.md](ENVIRONMENT_README.md).



---



## Tear down



```bash

cd bootstrap/output/$ENV

cdk destroy "$ENV-stack-b" "$ENV-stack-a" --app "python app.py" --output . --profile "$AWS_PROFILE"

```



The account-level OIDC provider is **not** deleted (shared across environments).

