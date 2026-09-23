# Runbook — deploying the recorder to AWS

*Read this before you start.* It walks the whole sequence in `infra/recorder_stack.py` (S2.5
Task 13, spec S9.2) into a running nightly job on AWS: install the tools, create the stack,
get an image into it, point CI at it, move the bridge's data over, and prove one night's run
actually works before trusting the schedule.

Every term in **bold** the first time it appears is in the glossary at the end. The commands
below all use `--profile ntsb` — the command-line identity `docs/runbooks/aws-setup.md`
created, which reaches the project's own AWS account, never the account holding `floyda.dev`.

---

## Before you start

- `docs/runbooks/aws-setup.md`'s checks all pass (the project account exists, the `ntsb`
  profile targets it, the budget is in place).
- `docs/runbooks/recorder-bridge.md`'s bridge is running on your Mac — stage 7 below stops it.
- **You do need Docker for this runbook**, once (stage 5): the very first image has to be
  built and pushed by hand, before CI can take over. Stage 1 checks for it.

---

## Stage 1 — Install the tools

Three things, all one-time (or check-only if already installed):

**1. Node.js and the CDK command-line tool.**

```
brew install node aws-cdk
```

(or, if you already have Node: `npm install -g aws-cdk`.)

```
cdk --version
```

**How to check.** The printed version should be at least `2.270.0` — the same `aws-cdk-lib`
version pinned in this checkout's `uv.lock`. A much older CDK CLI can fail to understand a
newer stack; a newer CLI (like the one already on this Mac) is fine.

**2. Docker Desktop**, for stage 5's one-time manual image upload.

```
open -a Docker
docker info
```

**How to check.** `docker info` prints without an error (it fails fast if Docker Desktop is
not running yet — give it a few seconds to start after `open -a Docker` and try again).

**3. This checkout's own Python dependencies.**

```
uv sync
```

**What this does.** Installs `aws-cdk-lib` and `constructs` — the Python libraries
`infra/recorder_stack.py` is written against — into this checkout's virtual environment,
alongside everything else the project already needs.

**What it costs.** Nothing; all three only touch your Mac.

**How to check.**

```
cd infra
cdk synth
```

Expect it to finish with no error and no prompt — `cdk synth` only renders the stack's
CloudFormation template locally; it makes no AWS call and needs no credentials, so this works
even before stage 2. (A short `cdk flags` notice about "unconfigured feature flags" is normal
and harmless.)

---

## Stage 2 — Bootstrap the account (once)

A CDK **stack** (the AWS resources `infra/recorder_stack.py` describes) has to be uploaded
somewhere before it can be deployed. **Bootstrap** creates that "somewhere": a small S3 bucket
to hold uploaded stack templates, an ECR repository CDK itself uses for its own assets, and a
handful of IAM roles CDK uses to deploy anything at all. This is a one-time setup per AWS
account and region — you will not run this again for future changes to the stack.

```
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
`--cli-input-json`, through `uv run python` (not a bare `python3` — this checkout pins its own
Python via `uv`, and a bare `python3` on macOS can trigger an "install the Command Line Tools?"
prompt on a Mac that has never needed one before):

```
pass show api/ntsb | head -n1 | uv run python -c '
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
part). At the end, CDK prints the stack's six outputs:

```
NtsbRecorderStack.BucketName = ...
NtsbRecorderStack.LogGroupName = /ecs/ntsb-recorder
NtsbRecorderStack.DeployRoleArn = arn:aws:iam::...:role/...
NtsbRecorderStack.RepositoryUri = ...dkr.ecr.eu-west-2.amazonaws.com/ntsb-recorder
NtsbRecorderStack.SubnetIds = subnet-...,subnet-...
NtsbRecorderStack.SecurityGroupId = sg-...
```

Keep this terminal output — every later stage needs one or more of these values. (You can also
get them again at any time: `aws cloudformation describe-stacks --stack-name
NtsbRecorderStack --profile ntsb --query 'Stacks[0].Outputs' --no-cli-pager`.)

**What it costs.** Nothing extra to deploy the stack itself (CloudFormation is free); the
resources it creates start billing once they exist — see "What it costs", below, for the
running total.

**How to check.**

```
aws cloudformation describe-stacks --stack-name NtsbRecorderStack --profile ntsb --query 'Stacks[0].StackStatus'
```

Expect `"CREATE_COMPLETE"` (or `"UPDATE_COMPLETE"` on a later re-deploy).

**Important: the 03:00 UTC schedule is live from the moment this command finishes**, and the
registry it points at is still empty — nothing has pushed an image yet (stage 5 does that).
**A run before the image exists fails, and fails with no log line at all** (there is nothing to
write a log stream, because the container image itself could not be pulled): finish stage 5
the same day you run stage 4, or before 03:00 UTC, whichever comes first.

---

## Stage 5 — Upload the first image by hand

*This stage exists because of a decision Andy made on 2026-09-23, logged as a Deviation.* CI's
`image-push` job (`.github/workflows/ci.yml`) only runs on a push to `main`, and this whole
stage only merges to `main` once its own done-criteria are met — so the very first image has to
reach ECR another way, or the schedule (live since stage 4) runs against an empty registry.

**1. Start Docker Desktop and confirm it is running** (stage 1 already did this once; repeat if
it has since quit):

```
open -a Docker
docker info
```

**2. Log in to ECR.** The registry is the part of `RepositoryUri` (stage 4's output) before the
first `/` — for example, if `RepositoryUri` is
`123456789012.dkr.ecr.eu-west-2.amazonaws.com/ntsb-recorder`, the registry is
`123456789012.dkr.ecr.eu-west-2.amazonaws.com`:

```
aws ecr get-login-password --region eu-west-2 --profile ntsb | docker login --username AWS --password-stdin <registry>
```

**What this does.** Gets a short-lived (12-hour) login token from ECR and hands it straight to
`docker login` on `stdin` — the token never sits in a shell variable or a command's own
argument list.

**3. Build the image, for the platform Fargate actually runs, not your Mac's.** The task
definition does not set `runtime_platform`, so it defaults to the standard Fargate platform,
`linux/x86_64` — the CPU family used in Intel and AMD servers. Docker Desktop on an Apple
Silicon Mac builds for your Mac's own chip, `arm64`, by default. If you build without saying
otherwise, the image runs fine locally and then **fails immediately** on Fargate — the CPU
instructions in the image do not match the CPU running it, and the container never starts.
`--platform linux/amd64` (Docker's name for the same x86_64 family) is therefore **required**,
not optional, from an Apple Silicon Mac:

```
short_sha=$(git -C /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause rev-parse --short HEAD)
docker build --platform linux/amd64 \
  --build-arg COMMIT_SHA="$short_sha" \
  -t <RepositoryUri>:latest \
  -t <RepositoryUri>:"$short_sha" \
  /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause
```

(Point the `git -C` path and the final build-context path at whichever checkout of this
repository holds the commit you want deployed — the S2.5 worktree while this stage is still on
its own branch, the main checkout after it merges.)

**4. Push both tags.**

```
docker push <RepositoryUri>:latest
docker push <RepositoryUri>:"$short_sha"
```

**What it costs.** Nothing for the build itself; ECR storage is in "What it costs" below.

**How to check.**

```
aws ecr describe-images --repository-name ntsb-recorder --region eu-west-2 --profile ntsb
```

Expect two `imageTags` entries covering the two tags just pushed (`latest` and the short SHA);
`imageScanStatus` may still read `IN_PROGRESS` for a minute after the push — that is normal.

**Until this stage's pull request merges to `main`, a code change needs this whole stage
repeated** — CI is not pushing yet. **After the merge, stage 6 hands that job to CI**, and this
manual upload is never needed again for an ordinary code change.

---

## Stage 6 — Point CI at the deploy role, then merge

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

**Then merge this stage's pull request to `main`.** `.github/workflows/ci.yml`'s `image-push`
job runs on every push to `main`; once `AWS_DEPLOY_ROLE_ARN` is set, it stops skipping and
builds and pushes `ntsb-recorder:latest` (and a tag matching the commit's short SHA) to ECR on
every future merge. Check the run in the "Actions" tab of the repository — the `image-push` job
should succeed, not be skipped.

---

## Stage 7 — Move the bridge's data to AWS

The bridge (`docs/runbooks/recorder-bridge.md`) has been writing to a **local** SQLite file
since the day the recorder merged. Move it to AWS now, in this order, so the cloud run
continues from where the bridge left off rather than starting from an empty store.

**Never run this stage between 03:00 and 04:30 UTC.** That is the scheduled task's own run
window (03:00 UTC start, 90-minute limit); a manual upload racing against the schedule's own
download/upload of the same object is exactly the "two writers" situation the whole design
avoids elsewhere. Pick any other time.

**1. Stop the bridge**, so nothing on the Mac writes to the local file again:

```
launchctl bootout gui/$(id -u)/dev.floyda.ntsb-record
```

**2. Check for an unflushed write-ahead log.** SQLite (`store/db.py`) opens every store in WAL
mode, which can leave recent writes sitting in a separate `-wal` file rather than in the main
file — a plain `cp`/`s3 cp` of the main file alone could then miss them:

```
ls -l /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/recorder.sqlite-wal
```

**If that file exists and is non-empty**, force everything into the main file before copying
anything:

```
sqlite3 /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/recorder.sqlite 'PRAGMA wal_checkpoint(TRUNCATE);'
```

(If the file does not exist, or is `0` bytes, skip this — there is nothing to checkpoint.)

**3. Upload the store.**

```
aws s3 cp /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/recorder.sqlite \
  s3://<BucketName from stage 4>/recorder.sqlite --profile ntsb
```

**4. Verify the upload is byte-for-byte complete** — do not trust a silent success alone:

```
aws s3api head-object --bucket <BucketName> --key recorder.sqlite --profile ntsb --query ContentLength --output text
stat -f%z /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/recorder.sqlite
```

**How to check.** The two numbers printed above must be identical. If they differ, do not
proceed — re-run the `aws s3 cp` and check again.

**What it costs.** A few cents at most for the transfer; the object's own ongoing storage cost
is in "What it costs" below.

**Once this stage's upload is verified, do not run the bridge again** — its `launchd` job is
already stopped (step 1); leaving it stopped is what keeps this from becoming two writers again.
(`rm ~/Library/LaunchAgents/dev.floyda.ntsb-record.plist` afterwards if you want it gone for
good, not just stopped; `rm -r "$HOME/Library/Application Support/ntsb-record"` removes the
installed wrapper script too — neither is required, since a stopped job runs nothing further
either way.)

---

## Stage 8 — Run one task by hand

Before trusting the 03:00 schedule, run the task once yourself and read its log. The cluster
and task family are both named `ntsb-recorder` (fixed in the stack); the subnets and security
group come straight from stage 4's `SubnetIds` and `SecurityGroupId` outputs — no separate
lookup needed:

```
aws ecs run-task \
  --cluster ntsb-recorder \
  --task-definition ntsb-recorder \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<SubnetIds, comma-split>],securityGroups=[<SecurityGroupId>],assignPublicIp=ENABLED}" \
  --profile ntsb --no-cli-pager --query 'tasks[0].taskArn' --output text
```

**What this does.** Starts the container once, immediately, outside the 03:00 schedule — the
same image, same command, same 90-minute limit as a real night. `--query 'tasks[0].taskArn'
--output text` prints just the task's ARN, ready to paste into the next command.

**What it costs.** A few cents at most — Fargate bills by the second while the task runs (see
"What it costs" below), and this one task is over in minutes for a store with little in it yet.

**How to check.** Two ways:

1. **The task's own status, including why it stopped:**

   ```
   aws ecs describe-tasks --cluster ntsb-recorder --tasks <taskArn from run-task's output> \
     --profile ntsb --no-cli-pager --query 'tasks[0].[lastStatus,stoppedReason,containers[0].exitCode]'
   ```

   Poll until `lastStatus` reads `"STOPPED"`. `exitCode` of `0` is success. **`stoppedReason` is
   the field that explains a failure that leaves no log at all** — an image the task could not
   pull (a typo in the tag, or stage 5/6 not actually done yet) or a secret it could not read
   (Parameter Store) both stop the task before it ever starts logging, and only `stoppedReason`
   says which.

2. **The log, in the CloudWatch console** (region **Europe (London), `eu-west-2`** — the region
   selector is in the console's top-right corner): CloudWatch → Log groups → `/ecs/ntsb-recorder`
   → the one log stream (named `recorder/recorder/<task id>`). Expect one line per case, ending
   with a `run done` summary line (spec S9.1's format: `run done cases=N changed=N new_docs=N
   failed=N ... minutes=N`). No case text ever appears in the log (spec S9.1) — only counts and
   outcomes.

---

## Stage 9 — Confirm the first scheduled run

The 03:00 UTC schedule is now the only thing that should ever write to the store. The morning
after the first 03:00 UTC has passed:

```
aws logs tail /ecs/ntsb-recorder --since 24h --profile ntsb
```

**What this does.** Prints the last 24 hours of the recorder's log lines directly in your
terminal — the same content stage 8 read from the console, without opening a browser.

**How to check.** A `run done` line with today's date, and no `failed=` count higher than a
handful of cases (some failures — a docket temporarily unreachable, a malformed PDF — are
normal and already counted; a large number is not). **Nothing alerts you if a night is
missed entirely** (no task started, so no failure to alert on either) — check the log
yourself after the first few nights, until the pattern is familiar.

---

## Stage 10 — Tearing the stack down (if you ever need to)

```
cd infra
cdk destroy --profile ntsb
```

**What survives, and why.** Three resources are created with `RemovalPolicy.RETAIN`
(`infra/recorder_stack.py`) — CloudFormation is not allowed to delete them, so `cdk destroy`
leaves all three in place even though it deletes everything else (the VPC, the task definition,
the schedule, the IAM roles):

- **The S3 bucket** — `recorder.sqlite` and every prior night's version.
- **The ECR repository** (`ntsb-recorder`) — every image CI (or stage 5) has pushed.
- **The CloudWatch log group** (`/ecs/ntsb-recorder`) — the last 30 days of log lines.

None of the three is deleted by accident, and none of the three is deleted on purpose by this
command either — you would delete them yourself, deliberately, if you ever wanted them gone.

**If you plan to redeploy afterwards, read this first — it is not automatic.**

The ECR repository and the log group keep the **same fixed name** every time
(`ntsb-recorder`, `/ecs/ntsb-recorder`) — that is deliberate (it is what lets stage 8's manual
run and CI's `image-push` refer to them by name instead of looking them up). It also means a
fresh `cdk deploy` after a `cdk destroy` tries to *create* a repository and a log group with
names that **already exist** (the retained, now-orphaned ones from before) and fails. The
practical, low-stakes recovery — appropriate here because the retained data in both is
disposable (ECR only ever keeps the newest 5 images anyway, all rebuildable from git history and
a fresh CI push; CloudWatch log lines are 30 days of operational output, not a record this
project keeps) — is to delete the two orphans first, then redeploy:

```
aws ecr delete-repository --repository-name ntsb-recorder --force --region eu-west-2 --profile ntsb
aws logs delete-log-group --log-group-name /ecs/ntsb-recorder --region eu-west-2 --profile ntsb
cdk deploy --profile ntsb
```

**The S3 bucket is a different case, and matters much more.** It has no fixed name (CDK
generates one), so a fresh `cdk deploy` does **not** collide with the orphaned bucket — it
simply creates a **new, different, empty** bucket. The recorder would then start its next
scheduled run against that empty store, silently, with no error — losing continuity with every
night recorded before the destroy, even though the old bucket (still retained) still has all of
it. **Before trusting the schedule again, copy the store across, the same way stage 7 first
moved it from the bridge:**

```
aws s3 ls --profile ntsb | grep -i ntsbrecorderstack   # find the OLD, orphaned bucket's name
aws s3 cp s3://<old bucket>/recorder.sqlite s3://<new BucketName from the fresh deploy's output>/recorder.sqlite --profile ntsb
```

Verify with the same `head-object`/`stat` comparison stage 7 uses, then the new bucket has
everything the old one did.

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
becomes one each time `run-task` (by hand, stage 8) or the schedule (stage 9) starts it.

**OIDC (OpenID Connect).** The mechanism GitHub Actions uses to prove its identity to AWS for
one workflow run, without any stored AWS access key: GitHub issues a short-lived signed token,
and the deploy role's trust policy (`infra/recorder_stack.py`) only accepts one naming this
exact repository and the `main` branch.

**Lifecycle rule.** A standing instruction attached to a bucket or a registry that
automatically expires or deletes old data on its own — here, old S3 object versions after 30
days, and all but the 5 newest container images.

**Retention (CloudWatch Logs).** How long log lines are kept before AWS deletes them
automatically — 30 days here (spec S9.1).

**Platform (Docker).** The CPU family and operating system an image is built for —
`linux/amd64` (Intel/AMD-compatible, what Fargate runs here) and `linux/arm64` (what an Apple
Silicon Mac builds by default) are not interchangeable; an image built for one fails outright
on the other.
