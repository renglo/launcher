# Setting up the Cloud dependencies


#### 1. Create a Virtual Environment if it doesn't exist

```
mkdir launcher
cd launcher
python3.12 -m venv launch-venv
source launch-venv/bin/activate
```

#### 2. Install dependencies

```
pip install boto3 opensearch-py
```

(opensearch-py is required only if you use the OpenSearch index step)


#### 3. List available AWS profiles. There should be at least one

```
aws configure list-profiles
```

You should see the profile that points to the cloud you want to deploy this to. 


#### 4. Run the deploy environment for TT
This will create the Dynamo tables, create the Cognito user pool, create the IAM policy, create the Role and link everything together.
It now also bootstraps GitHub OIDC deploy roles and provisions backend infra (ECR/Lambda/API Gateway/WebSocket) for one tenant at a time.
Backend infra is provisioned for both `production` and `staging` stages, with a Lambda alias per stage.
CodeDeploy deployment groups are provisioned too: `production` uses `CodeDeployDefault.LambdaCanary10Percent10Minutes` and `staging` uses `CodeDeployDefault.LambdaAllAtOnce`.
Replace <environment_name> with the actual name of the environment you want to create. Replace <aws_profile> 

```
cd scripts
python deploy_environment.py <environment_name> --aws-region <aws_region> --aws-profile <aws_profile> --github-repo <org/repo>
```

Optional flags:

```
--disable-staging-role
--enable-cdk-bootstrap
--seed-image-uri <account>.dkr.ecr.<region>.amazonaws.com/<repo>:<tag>
--dry-run
```

Note on CDK bootstrap:
- By default, CDK bootstrap is skipped because the current launcher flow provisions infrastructure using SDK scripts.
- `--enable-cdk-bootstrap` is optional today and intended for forward compatibility, since the target architecture is to migrate fully to CDK deploy flows in the future.

Seed image note:
- First-time backend Lambda creation requires a valid Lambda container image in ECR.
- A minimal seed image is provided at `scripts/backend/seed-image/` using `public.ecr.aws/lambda/python:3.12`.
- `deploy_environment.py` now builds/pushes that seed image automatically when the backend Lambda does not exist.
- `--seed-image-uri` remains available as an optional override if you want to use a custom seed image.


**OpenSearch:** The deploy creates the index automatically. It uses provisioned domain `{env}-search` if it exists, otherwise creates OpenSearch Serverless collection `{env}-collection` with required policies. No manual setup needed.


Standalone: `python create_opensearch_index.py <env_name> --aws-profile <aws_profile> --aws-region <region>`


 NEXT STEPS
The next step is to run the Zappa installer. Go back to the document ../CLOUD_README.md

Bring with you the following information and the terminal output of the deploy_environment.py run
a. <aws_region>
b. <bucket_name>
c. <cognito_user_pool_id>
d. <cognito_app_client_id>
e. OPENSEARCH_ENDPOINT, OPENSEARCH_INDEX (if OpenSearch step was run)




### 5. Create the Config files 

 
`env_config.py` 

    DYNAMODB_ENTITY_TABLE = '<name>_entities'
    DYNAMODB_BLUEPRINT_TABLE = '<name>_blueprints'
    DYNAMODB_RINGDATA_TABLE = '<name>_data'
    DYNAMODB_REL_TABLE = '<name>_rel'
    DYNAMODB_CHAT_TABLE = '<name>_chat'

Enter random long strings in the CSRF and SECRET KEYS

    CSRF_SESSION_KEY = '<xxxxx>'
    SECRET_KEY = '<xxxxx>'

Enter the region and cognito ids

    COGNITO_REGION = '<us-xxxx-x>'
    COGNITO_USERPOOL_ID = '<us-xxxx-1_xxxxxxx>'
    COGNITO_APP_CLIENT_ID = '<xxxxx>'

Enter the bucket name

    S3_BUCKET_NAME = '<name>-xxxxx'

WebSocket values are now generated automatically:

    WEBSOCKET_CONNECTIONS = 'https://<id>.execute-api.<region>.amazonaws.com/production/'
    VITE_WEBSOCKET_URL = 'wss://<id>.execute-api.<region>.amazonaws.com/production/'
    WEBSOCKET_CONNECTIONS_STAGING = 'https://<id>.execute-api.<region>.amazonaws.com/staging/'
    VITE_WEBSOCKET_URL_STAGING = 'wss://<id>.execute-api.<region>.amazonaws.com/staging/'

If OpenSearch was configured, add:

    OPENSEARCH_ENDPOINT = 'https://search-xxx.us-east-1.es.amazonaws.com'
    OPENSEARCH_INDEX = '<env>-documents'

Place this file in /system


In `.env.development.*` and `.env.production.*`

Enter the region and cognito ids (again)

    VITE_COGNITO_REGION='<us-xxxx-x>'
    VITE_COGNITO_USERPOOL_ID='<us-xxxx-1_xxxxxxx>'
    VITE_COGNITO_APP_CLIENT_ID='<xxxxx>'


Place these files in /console


### 6. Setup an initial Local Environment

An initial Local Environment needs to be setup and deployed to generate the missing services. 

For this you'll have to create a local environment, configure it and deploy it. Follow the instructions in the system README.md

```
https://github.com/renglo/system/blob/main/README.md
```

Once you have the local environment up and running, go to the next step


### 7. Preparing the initial Local Environment for deployment

Install Zappa

Initialize the virtual environment in system
```
deactivate
cd system
source venv/bin/activate
```

```
pip install zappa
pip install setuptools
```

Create the file:  system/zappa_settings.json

Include the environment variables here as env_config.py won't be sent in the package (this is for security reasons)

Assuming the environment is called xyz

```zappa_settings.json
{
    "xyz_1": {
        "app_function": "application.app",
        "aws_region": "us-east-1",
        "project_name": "renglo",
        "runtime": "python3.12",
        
        "environment_variables": {
            "WL_NAME": "xyz",
            
            "BASE_URL": "https://xyz.renglo.com",
            "FE_BASE_URL": "https://xyz-console.renglo.com",
            "DOC_BASE_URL": "https://xyz.renglo.com",

            "APP_FE_BASE_URL": "https://xyz.renglo.com",

            "API_GATEWAY_ARN" : "arn:aws:execute-api:us-east-1:*:*",
            "ROLE_ARN" : "arn:aws:iam::*:role/xyz_tt_role",
            "SYS_ENV": "xyz",

            "DYNAMODB_ENTITY_TABLE": "xyz_entities",
            "DYNAMODB_BLUEPRINT_TABLE": "xyz_blueprints",
            "DYNAMODB_RINGDATA_TABLE": "xyz_data",
            "DYNAMODB_REL_TABLE": "xyz_rel",
            "DYNAMODB_CHAT_TABLE": "xyz_chat",

            "CSRF_SESSION_KEY" : "123456",
            "SECRET_KEY" : "678909",

            "COGNITO_REGION": "us-east-1",
            "COGNITO_USERPOOL_ID": "us-east-1_xxxxx",
            "COGNITO_APP_CLIENT_ID": "yyyyy",
            "COGNITO_CHECK_TOKEN_EXPIRATION": "True",

            "PREVIEW_LAYER" : "2",

            "S3_BUCKET_NAME": "xyz-12345",

            "OPENAI_API_KEY" : "sk-proj-qwerty",
            "WEBSOCKET_CONNECTIONS" : "https://xyz.execute-api.us-east-1.amazonaws.com/test",
            "ALLOW_DEV_ORIGINS" : "true"
        },
        
               
        "exclude": [
            "boto3",
            "dateutil",
            "botocore",
            "s3transfer",
            "concurrent",
            "*.pyc",
            "__pycache__/*",
            "venv/*",
            ".git/*",
            ".pytest_cache/*",
            "*.md",
            "tests/*",
            "env_config.py",
            "env_config.py.TEMPLATE"
        ],
        
        "profile_name": "your-profile",
        "domain": "xyz.renglo.com",
        "s3_bucket": "xyz-79668783",
        "slim_handler": true,
        "static_support": true,
        "manage_roles": false,
        "role_name": "xyz_tt_role"
    }
}
```

Run 
```
zappa deploy xyz_1
```

It is going to upload the files and create the service but it will fail to initialize. That is ok. 

Run the update script
```
./zappa_update.sh xyz_1 update
```


You get something like this:

```
Deploying API Gateway..
Waiting for lambda function [x-prod] to be updated...
Deployment complete!: https://<id>.execute-api.<aws_region>.amazonaws.com/<environment_name>_<dev|test|prod>
```


You should be able to test whether the app is running by going to 

`https://<id>.execute-api.<aws_region>.amazonaws.com/<environment_name>_<dev|test|prod>/timex` 

 It should return the server time. 

 You won't be able to access the Application yet, because this url is already using the first position in the path. Tank and Tower depend on the URL for their routing


### Step 6: Setup a customized domain

Setup the API to accept custom domains
- Go to the AWS console > API Gateway and create a new Custom Domain Name

`Domain name = <environment_name>.renglo.com`

- Select a new subdomain under an existing ACM Certificate. 
- If you must use a new domain, you need to create the ACM certificate first (out of the scope of this document)
- Create a  Custom Domain and go to the API mappings. You'll be able to select the API that you just deployed and the stage, save that. 
- This alone won't automatically redirect all traffic to your application. You still need to create a CN Record in your domain.

Configure domain to point to API Gateway


- To get the right value, go to API Gateway > Custom Domain Names 
- Select the Custom Domain Name and look for "API Gateway domain name" and copy it as is.
- Go to Route53>Zones and Create a CNAME record:

`NAME=<environment_name>`  `VALUE=<domain_name_api_id>.execute-api.<aws_region>.amazonaws.com>`

VERY IMPORTANT: The value of the CNAME should not be the GATEWAY URL but the CUSTOM DOMAIN URL. They look similar but they are not the same

- Save that record and almost immediately you'll be able to see your app in that subdomain. 

TROUBLESHOOT: 
-If you find a blank screen, double check your tank and tower configuration files have the domain you just configured. 
- If you are using Chrome, it won't work immediately even if you close the window, refresh everything. Try in another browser. Eventually, Chrome will consult the new DNS records and show you the page. 





### Step 7: Setting up the WebSocket API

Manual Process

- Go to API Gateway in the AWS Console
- Create  a new API  APIs > Create API > WebSocket API > Build

Step 1 > API details
API name: <api_name>  //This is the api name, it can be called anything
Route selection expression: $request.body.action
IP address type: IPv4

Step 2 > Routes
Select Add Custom Route
Route key:  chat_message

Step 3 > Integrations

Integration type: HTTP
Method: POST
URL endpoint: <integration_target>

NOTE >> The “integration_target_base” is the URL of the stage in the REST api (which was automatically created by Zappa) on deployment. 
It is the same URL that appears when you deploy something with Zappa
- a. Select the RESTful API in the API Gateway
- b. Go to the Stages section
- c. Look for the Invoke URL


integration_target = integration_target_base + "/_chat/message"

Example: "https://abcdef1234.execute-api.us-east-1.amazonaws.com/something_prod_0305a/_chat/message"

Step 4 > Stages
Stage name: <environment>  (prod|dev)

Once the API is saved. Click on the Route called chat_message,  go to Integration Request tab and enter the following template

Name: message_template
```
#set($inputRoot = $input.path('$'))
{
  "action": "$inputRoot.action",
  "data": "$inputRoot.data",
  "entity_type": "$inputRoot.entity_type",
  "entity_id": "$inputRoot.entity_id",
  "thread": "$inputRoot.thread",
  "portfolio": "$inputRoot.portfolio",
  "org": "$inputRoot.org",
  "core": "$inputRoot.core",
  "next": "$inputRoot.next",
  "connectionId": "$context.connectionId",
  "auth": "$inputRoot.auth"
}

```

Add the name of the template ("message_template") to the Template selection expression

IMPORTANT: Every time you make a change in the templates or routes, you need to click on "Deploy API" otherwise the changes won't reflect.


-----------------
Steps 1-4 could have been automatically done by running this command

Go to /tank/installer and run

```
python create_websocket_api.py <api_name> "<integration_target>" "<endpoint>" <environment> --aws-profile <profile>
```

Example_Usage:
python create_websocket_api.py x_prod_1234a_websocket "chat_message" "https://qwerty123.execute-api.us-east-1.amazonaws.com/x_prod_1234a/_chat/message" prod --aws-profile volatour


Go to the Stages section in the new WebSocket API (just created) and looks for:

WebSocket URL and @connections URL . Copy them somewhere
------------------


Step 5 > Tell the FrontEnd and BackEnd where to connect to the WebSocket

Go to the Stages section on the left menu, 
Select the environment you just created (dev|prod)

Look for the Connections URL. 
It looks like this: https://abc123.execute-api.us-east-1.amazonaws.com/dev/@connections

Open tank/env_config.py and paste the @connections URL in the constant called WEBSOCKET_CONNECTIONS without the "/@connections" part at the end. 


Look for the WebSocket URL
It looks like this: wss://abc123.execute-api.us-east-1.amazonaws.com/dev/

Open tower/.env.production and tower/.env.development and paste the WebSocket URL as is

In the "Integration request settings"
IMPORTANT: Check that HTTP proxy integration Info is set to: False
IMPORTANT: Check that the Content Handling is set to : Convert to Text

