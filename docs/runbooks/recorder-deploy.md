# Runbook — deploying the recorder to AWS

*Read this before you start.* It walks the whole sequence in `infra/recorder_stack.py` (S2.5
Task 13, spec S9.2) into a running nightly job on AWS: install the tools, create the stack,
point CI at it, and prove one night's run actually works before trusting the schedule.

Every term in **bold** the first time it appears is in the glossary at the end. The commands
below all use `--profile ntsb` — the command-line identity `docs/runbooks/aws-setup.md`
created, which reaches the project's own AWS account, never the account holding `floyda.dev`.

---

## Before you start

- `docs/runbooks/aws-setup.md`'s checks all pass (the project account exists, the `ntsb`
  profile targets it, the budget is in place).
- `docs/runbooks/recorder-bridge.md`'s bridge is running on your Mac — stage 8 below stops it
  once AWS takes over.
- You do **not** need Docker installed for anything in this runbook. The stack creates an empty
  image registry; GitHub Actions builds and pushes the actual image (stage 4).

---

## Stage 1 — Install the CDK dependencies

```
uv sync
```

**What this does.** Installs `aws-cdk-lib` and `constructs` — the Python libraries
`infra/recorder_stack.py` is written against — into this checkout's virtual environment,
alongside everything else the project already needs.

**What it costs.** Nothing; this only touches your Mac.

**How to check.** `cd infra && cdk synth` (below) succeeds.

---

## Stage 2 — Bootstrap the account (once)

A CDK **stack** (the AWS resources `infra/recorder_stack.py` describes) has to be uploaded
somewhere before it can be deployed. **Bootstrap** creates that "somewhere": a small S3 bucket
to hold uploaded stack templates, an ECR repository CDK itself uses for its own assets, and a
handful of IAM roles CDK uses to deploy anything at all. This is a one-time setup per AWS
account and region — you will not run this again for future changes to the stack.

```
cd infra
cdk bootstrap aws://$(aws sts get-caller-identity --profile ntsb --query Account --output text)/eu-west-2 --profile ntsb
```

**What this does.** Creates the bootstrap bucket, ECR repository and IAM roles above, in the
project account, region `eu-west-2`.

**What it costs.** A few cents a month at this project's scale — the bootstrap bucket holds a
handful of small template files, nothing else.

**How to check.**

```
aws cloudformation describe-stacks --stack-name CDKToolkit --profile ntsb --query 'Stacks[0].StackStatus'
```

Expect `"CREATE_COMPLETE"`.

---

## Stage 3 — Put the NTSB API key in Parameter Store

The recorder's task reads its NTSB API key from AWS **Parameter Store** at start (decision
0069) — the stack never holds the key itself (`infra/recorder_stack.py` only references the
parameter's *name*, `/ntsb/api-key`). You write the real value once, by hand, from `pass`.

**Why not the simpler one-line command.** The obvious command is

```
aws ssm put-parameter --name /ntsb/api-key --type SecureString --value "$(pass show api/ntsb | head -n1)" --profile ntsb
```

and it works — but for the moment `aws` runs, the key sits in that command's own argument
list, which (on a machine with more than one user, or any tool that samples the process table)
is visible via `ps`. This project's standing rule is that a key never reaches a printed line or
anywhere else it doesn't have to; the command below keeps the same effect while never putting
the key on a command line at all. It builds the request as JSON on `stdin` instead, using
`--cli-input-json`:

```
pass show api/ntsb | head -n1 | python3 -c '
import json, sys
value = sys.stdin.readline().rstrip("\n")
print(json.dumps({"Name": "/ntsb/api-key", "Type": "SecureString", "Value": value}))
' | aws ssm put-parameter --cli-input-json file:///dev/stdin --profile ntsb
```

**What this does.** Reads the key from your password store, writes it to AWS Parameter Store
as an encrypted (`SecureString`) parameter named `/ntsb/api-key`, and prints nothing but the
new parameter's version number — never the key itself.

**What it costs.** Nothing; a standard parameter is free.

**How to check.**

```
aws ssm describe-parameters --profile ntsb --query "Parameters[?Name=='/ntsb/api-key']"
```

Expect one entry, `"Type": "SecureString"`. (Reading the value back would defeat the point —
this only confirms the parameter exists.)

**If you ever need to replace the key** (rotation), add `"Overwrite": true` to the JSON object
above; `put-parameter` refuses to overwrite an existing parameter by default.

---

## Stage 4 — Deploy the stack

### 4a — Check for an existing GitHub OIDC provider first

An AWS account can hold only **one** IAM **OIDC provider** per identity provider URL. Check
whether one already exists for GitHub Actions before deploying, so the stack imports it instead
of trying to create a duplicate (which CloudFormation would reject):

```
aws iam list-open-id-connect-providers --profile ntsb
```

- **If the list is empty**, skip to 4b — the stack creates the provider itself.
- **If an entry's ARN ends in `oidc-provider/token.actions.githubusercontent.com`**, note its
  full ARN and pass it as context in 4b:
  `cdk deploy --profile ntsb -c github_oidc_provider_arn=<that ARN>`.

### 4b — Deploy

```
cd infra   # if not already there
cdk deploy --profile ntsb
```

(Add `-c github_oidc_provider_arn=<arn>` from 4a if an existing provider was found.)

**What this prints.** First, the list of IAM changes the stack will make (new roles, what they
can do) — CDK always pauses here for security-sensitive changes and asks:

```
Do you wish to deploy these changes (y/n)?
```

Read the summary, then type `y`. Deployment takes a few minutes (creating a VPC is the slowest
part). At the end, CDK prints the stack's four outputs:

```
NtsbRecorderStack.BucketName = ...
NtsbRecorderStack.LogGroupName = /ecs/ntsb-recorder
NtsbRecorderStack.DeployRoleArn = arn:aws:iam::...:role/...
NtsbRecorderStack.RepositoryUri = ...dkr.ecr.eu-west-2.amazonaws.com/ntsb-recorder
```

Keep this terminal output — stage 5 needs `DeployRoleArn`, and stage 6 needs `RepositoryUri`
and `BucketName`.

**What it costs.** Nothing extra to deploy the stack itself (CloudFormation is free); the
resources it creates start billing once they exist — see "What it costs", below, for the
running total. The task definition references an image tag (`latest`) that does not exist in
the registry yet — that is expected and harmless; a task definition is just a description, and
nothing tries to run it until stage 6.

**How to check.**

```
aws cloudformation describe-stacks --stack-name NtsbRecorderStack --profile ntsb --query 'Stacks[0].StackStatus'
```

Expect `"CREATE_COMPLETE"` (or `"UPDATE_COMPLETE"` on a later re-deploy).

---

## Stage 5 — Point CI at the deploy role, then merge

GitHub Actions pushes the container image to ECR by assuming `DeployRoleArn` from stage 4 (no
stored AWS secret — see the glossary's **OIDC**). Tell the repository which role that is:

```
gh variable set AWS_DEPLOY_ROLE_ARN --body <DeployRoleArn from stage 4>
```

**What this does.** Sets a GitHub Actions repository variable (not a secret — the role ARN
identifies the role but grants nothing on its own; only a workflow run in *this* repository, on
`main`, can assume it, per the trust condition `infra/recorder_stack.py` sets).

**What it costs.** Nothing.

**How to check.**

```
gh variable list
```

Expect `AWS_DEPLOY_ROLE_ARN` in the list.

**Then merge this stage's pull request to `main`** (if not already merged). `.github/workflows/
ci.yml`'s `image-push` job runs on every push to `main`; once `AWS_DEPLOY_ROLE_ARN` is set, it
stops skipping and builds and pushes `ntsb-recorder:latest` (and a tag matching the commit's
short SHA) to ECR. Check the run in the "Actions" tab of the repository — the `image-push` job
should succeed, not be skipped.

---

## Stage 6 — Run one task by hand

Before trusting the 03:00 schedule, run the task once yourself and read its log. The cluster
and task family are both named `ntsb-recorder` (fixed in the stack, so no lookup is needed for
those two); the subnets and security group are generated, so look them up first:

```
aws cloudformation describe-stack-resources --stack-name NtsbRecorderStack --profile ntsb \
  --query "StackResources[?ResourceType=='AWS::EC2::Subnet'].PhysicalResourceId" --output text
```

```
aws cloudformation describe-stack-resources --stack-name NtsbRecorderStack --profile ntsb \
  --query "StackResources[?ResourceType=='AWS::EC2::SecurityGroup'].PhysicalResourceId" --output text
```

The first prints two subnet IDs (`subnet-...`); the second prints one security group ID
(`sg-...`). Then:

```
aws ecs run-task \
  --cluster ntsb-recorder \
  --task-definition ntsb-recorder \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<subnet-1>,<subnet-2>],securityGroups=[<sg-id>],assignPublicIp=ENABLED}" \
  --profile ntsb
```

**What this does.** Starts the container once, immediately, outside the 03:00 schedule — the
same image, same command, same 90-minute limit as a real night.

**What it costs.** A few cents at most — Fargate bills by the second while the task runs (see
"What it costs" below), and this one task is over in minutes for a store with little in it yet.

**How to check.** Two ways:

1. **The task's own status:**

   ```
   aws ecs describe-tasks --cluster ntsb-recorder --tasks <taskArn from run-task's output> --profile ntsb --query 'tasks[0].lastStatus'
   ```

   Poll until it reads `"STOPPED"`, then check `tasks[0].containers[0].exitCode` — `0` is
   success.

2. **The log, in the CloudWatch console:** CloudWatch → Log groups → `/ecs/ntsb-recorder` → the
   one log stream (named `recorder/recorder/<task id>`). Expect one line per case, ending with
   a `run done` summary line (spec S9.1's format: `run done cases=N changed=N new_docs=N
   failed=N ... minutes=N`). No case text ever appears in the log (spec S9.1) — only counts and
   outcomes.

---

## Stage 7 — Move the bridge's data to AWS

The bridge (`docs/runbooks/recorder-bridge.md`) has been writing to a **local** SQLite file
since the day the recorder merged. Move it to AWS *before* trusting the schedule, so the cloud
run continues from where the bridge left off rather than starting from an empty store — its own
stage 8 has the two commands (stop the bridge with `launchctl bootout`, then `aws s3 cp` the
local file to `s3://<BucketName from stage 4>/recorder.sqlite`). Do that now, then come back
here.

---

## Stage 8 — Confirm the first scheduled run

Once stage 7 is done, the 03:00 UTC schedule is the only thing writing to the store. The
morning after the first 03:00 UTC has passed:

```
aws logs tail /ecs/ntsb-recorder --since 24h --profile ntsb
```

**What this does.** Prints the last 24 hours of the recorder's log lines directly in your
terminal — the same content stage 6 read from the console, without opening a browser.

**How to check.** A `run done` line with today's date, and no `failed=` count higher than a
handful of cases (some failures — a docket temporarily unreachable, a malformed PDF — are
normal and already counted; a large number is not).

---

## Stage 9 — Tearing the stack down (if you ever need to)

```
cd infra
cdk destroy --profile ntsb
```

**What survives.** The S3 bucket (`recorder.sqlite` and every prior night's version) and the
ECR repository (every image CI has pushed) are both created with `RemovalPolicy.RETAIN`
(`infra/recorder_stack.py`) — CloudFormation is not allowed to delete them, so `cdk destroy`
leaves them in place even though it deletes everything else (the VPC, the task definition, the
schedule, the IAM roles). Delete them yourself, deliberately, if you ever want them gone too —
they are not deleted by accident either way.

---

## What it costs

Estimates. Spec S14.6 says the billed figures replace these at close-out — nothing here is
final.

| Resource | Estimate | Why |
|---|---|---|
| Fargate compute | ~$0.30/month | About 40 minutes a day (spec S9.1 estimate) at the smallest Fargate size, 0.25 vCPU / 0.5 GB. |
| Public IPv4 address | ~$0.005/hour while the task runs | AWS bills separately for the public IP `assign_public_ip=ENABLED` gives the task; at ~40 min/night this is under $0.15/month. |
| S3 (the store) | Under $0.10/month | `recorder.sqlite` is small; 30-day version expiry keeps it from growing indefinitely. |
| ECR (the image) | Under $0.10/month | 5 images kept at most (the lifecycle rule), each under 200 MB. |
| CloudWatch Logs | Under $0.10/month | 30-day retention, one line per case per night. |
| Parameter Store | Free | Standard (not "advanced") parameters have no charge. |
| EventBridge Scheduler | Free | One invocation a day is far inside the free tier. |
| **Total** | **~$0.50–$0.70/month** | Matches spec S9.4's estimate. |

---

## Glossary

**Bootstrap (CDK).** One-time preparation of an AWS account and region — a small S3 bucket, an
ECR repository, and IAM roles CDK needs before it can deploy anything.

**Stack.** The whole set of AWS resources one CDK Python file (`infra/recorder_stack.py`)
describes, deployed and torn down together, tracked as one CloudFormation stack
(`NtsbRecorderStack`).

**Task definition.** ECS's description of a container to run: which image, how much CPU and
memory, what environment variables and secrets, what command. Not itself a running thing — it
becomes one each time `run-task` (by hand, stage 6) or the schedule (stage 8) starts it.

**OIDC (OpenID Connect).** The mechanism GitHub Actions uses to prove its identity to AWS for
one workflow run, without any stored AWS access key: GitHub issues a short-lived signed token,
and the deploy role's trust policy (`infra/recorder_stack.py`) only accepts one naming this
exact repository and the `main` branch.

**Lifecycle rule.** A standing instruction attached to a bucket or a registry that
automatically expires or deletes old data on its own — here, old S3 object versions after 30
days, and all but the 5 newest container images.

**Retention (CloudWatch Logs).** How long log lines are kept before AWS deletes them
automatically — 30 days here (spec S9.1).
