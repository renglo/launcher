#!/usr/bin/env python3
import json
import os

import aws_cdk as cdk

from backend_lambda_stack import BackendLambdaStack


app = cdk.App()

env_name = app.node.try_get_context("env_name")
if not env_name:
    raise ValueError("Missing required CDK context: env_name")

stage = app.node.try_get_context("stage") or "production"
image_tag = app.node.try_get_context("image_tag")
if not image_tag:
    raise ValueError("Missing required CDK context: image_tag")

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region") or "us-east-1",
)

runtime_env_file = app.node.try_get_context("runtime_env_file")
runtime_env = {}
if runtime_env_file:
    with open(runtime_env_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    runtime_env = {str(k): str(v) for k, v in loaded.items()}

openai_api_key = os.environ.get("OPENAI_API_KEY")
if openai_api_key:
    runtime_env["OPENAI_API_KEY"] = openai_api_key

normalized_stage = stage.strip().lower()
if normalized_stage not in {"production", "staging"}:
    raise ValueError("Context 'stage' must be one of: production, staging")

stack_suffix = "Production" if normalized_stage == "production" else "Staging"
BackendLambdaStack(
    app,
    f"{env_name.capitalize()}{stack_suffix}Stack",
    env_name=env_name,
    stage_name=normalized_stage,
    image_tag=image_tag,
    runtime_env=runtime_env,
    env=env,
)

app.synth()
