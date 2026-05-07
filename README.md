README

If you want to install a new Renglo Environment use this:

ENVIRONMENT_README.md

Main command:

`python scripts/deploy_environment.py <environment_name> --aws-profile <profile> --aws-region <region> --github-repo <org/repo>`

CDK bootstrap is optional in the current SDK-based flow.
Use `--enable-cdk-bootstrap` only if you want to prepare the account for CDK deploy workflows.
The long-term intention is to migrate backend provisioning fully to CDK.

For first-time backend Lambda creation, the launcher automatically builds and pushes a minimal seed image from `scripts/backend/seed-image/`.
The launcher provisions backend resources for both `production` and `staging`, and configures one Lambda alias per stage.
It also provisions CodeDeploy (Lambda compute platform): `production` uses `CodeDeployDefault.LambdaCanary10Percent10Minutes` and `staging` uses `CodeDeployDefault.LambdaAllAtOnce`.
`--seed-image-uri` is optional and only needed to override that default seed image.



