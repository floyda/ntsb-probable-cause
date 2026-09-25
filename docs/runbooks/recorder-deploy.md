# Runbook — deploying the recorder to AWS

*Read this before you start.* It walks the whole sequence in `infra/recorder_stack.py` (S2.5
Task 13, spec S9.2) into a running nightly job on AWS: install the tools, create the stack,
get an image into it, move the bridge's data over, prove one night's run actually works, and
only then point CI at it.

Every term in **bold** the first time it appears is in the glossary at the end. The commands
below all use `--profile ntsb` — the command-line identity `docs/runbooks/aws-setup.md`
created, which reaches the project's own AWS account, never the account holding `floyda.dev`.

**A note on paths.** A few commands below need a checkout of this repository on disk — for
`git -C` and for a Docker build context. Right now, before this stage's pull request merges,
that is the S2.5 worktree:
`/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/.claude/worktrees/s25-recorder`.
**After the merge**, use the main checkout instead:
`/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause`. The commands below default to
the worktree path, since that is what this stage is run from; swap it for the main checkout
path the next time you deploy a later change.

---

## Before you start

- `docs/runbooks/aws-setup.md`'s checks all pass (the project account exists, the `ntsb`
  profile targets it, the budget is in place).
- `docs/runbooks/recorder-bridge.md`'s bridge is running on your Mac — stage 6 below stops it.
- **You do need Docker for this runbook**, once (stage 5): the very first image has to be
  built and pushed by hand, before CI can take over. Stage 1 checks for it.

---

## Console access

Everything below runs from the command line, but some checks are easier in a browser — and
getting to the right place in the console has one step that is easy to miss.

**The recorder lives in the project account, not the management account** (decision 0010).
Signing in normally puts you in the *management* account (the one that also holds
`floyda.dev`) — none of this stack's resources are there. **Root cannot switch roles either**,
so this has to be done as the IAM user, never as root (`docs/runbooks/aws-setup.md` stage 0
covers why root is avoided generally).

1. Sign in to the AWS console as the IAM user (the sign-in URL `docs/runbooks/aws-setup.md`
   stage 0 found).
2. Use **Switch role** (top-right corner, under the account menu) to move into the project
   account: account = the project account number from
   `docs/runbooks/aws-accounts.local.md` (not committed — account numbers never go in a
   tracked file), role = `OrganizationAccountAccessRole`. Filling in the same two values as a
   direct link also works:

   ```
   https://signin.aws.amazon.com/switchrole?account=<project account>&roleName=OrganizationAccountAccessRole&displayName=ntsb
   ```

3. **Check you actually landed in the project account** before trusting anything the console
   shows you:

   ```
   aws sts get-caller-identity --profile ntsb --region eu-west-2
   ```

   Compare the `Account` this prints against the account number shown in the console's own
   top-right account menu — they must match.

4. **The region must be `eu-west-2`** (the selector is next to the account menu). Every
   resource this stack creates lives only in that region (decision 0010); any other region
   shows an empty console with nothing to find, not an error.

### Where to look

| For | Go to |
|---|---|
| The recorder's log | CloudWatch → Log groups → `/ecs/ntsb-recorder` |
| Whether a task is running, or why one stopped | ECS → Clusters → `ntsb-recorder` → Tasks (toggle to show **stopped** tasks too — a failed task disappears from the default running-only view) |
| The schedule's off switch | EventBridge → Scheduler → Schedules → the one schedule → **Disable** (stops future nights without touching anything already deployed) |
| Rolling the store back to an earlier night | S3 → the bucket (stage 4's `BucketName`) → `recorder.sqlite` → **Versions** tab |
| The stack's outputs, without the CLI | CloudFormation → Stacks → `NtsbRecorderStack` → **Outputs** tab |
| The container images CI (or stage 5) has pushed | ECR → Repositories → `ntsb-recorder` |
| The stored API key (existence only) | Systems Manager → Parameter Store → `/ntsb/api-key` — **never click "Show"**; this runbook's own rule (stage 3) is that the key never appears on screen, including here |

**Costs.** Cost Explorer and Budgets are in the **management** account, not the project
account — **Switch back** first, then filter by linked account (the project account) to see
just this stack's spend. Two things to know going in: Cost Explorer can take **up to 24 hours**
to enable the first time it is opened in an account, and even once enabled, **costs lag by
about a day** — do not expect today's spend to appear today.

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

**A banner you can ignore.** The first command that starts the underlying Node process (`cdk
synth`, below, or any `cdk` command) may print a boxed warning that this software "has not
been tested with node v26" (or whatever version `brew` installed). This is jsii (the layer
that lets `aws-cdk-lib`, a Node library, be called from Python) being conservative about which
Node releases it has explicitly tested against, not a real compatibility problem — every `cdk
synth` run while building this stack used exactly this combination without issue. Ignore it
rather than installing an older Node just to silence it (`brew install node@24` would work if
you would rather not see the banner, but it is not necessary).

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

`cdk synth` prints the whole rendered CloudFormation template to your terminal — a few hundred
lines — followed by a `cdk flags` notice about "unconfigured feature flags" (harmless, ignore
it too). **Success is the command exiting with status `0` and the template containing lines
naming `NtsbRecorderStack`** (for example, `aws:cdk:path: NtsbRecorderStack/Store/Resource`)
— you do not need to read the whole thing to confirm it worked. This makes no AWS call and
needs no credentials, so it works even before stage 2.

---

## Stage 2 — Bootstrap the account (once)

A CDK **stack** (the AWS resources `infra/recorder_stack.py` describes) has to be uploaded
somewhere before it can be deployed. **Bootstrap** creates that "somewhere": a small S3 bucket
to hold uploaded stack templates, an ECR repository CDK itself uses for its own assets, and a
handful of IAM roles CDK uses to deploy anything at all. This is a one-time setup per AWS
account and region — you will not run this again for future changes to the stack.

```
cdk bootstrap aws://$(aws sts get-caller-identity --profile ntsb --region eu-west-2 --query Account --output text)/eu-west-2 --profile ntsb
```

**What this does.** Creates the bootstrap bucket, ECR repository and IAM roles above, in the
project account, region `eu-west-2`.

**What it costs.** A few cents a month at this project's scale — the bootstrap bucket holds a
handful of small template files, nothing else.

**How to check.**

```
aws cloudformation describe-stacks --stack-name CDKToolkit --profile ntsb --region eu-west-2 --query 'Stacks[0].StackStatus'
```

Expect `"CREATE_COMPLETE"`.

---

## Stage 3 — Put the NTSB API key in Parameter Store

The recorder's task reads its NTSB API key from AWS **Parameter Store** at start (decision
0069) — the stack never holds the key itself (`infra/recorder_stack.py` only references the
parameter's *name*, `/ntsb/api-key`). You write the real value once, by hand, from `pass`.

**Why not the simpler one-line command.** The obvious command is

```
aws ssm put-parameter --name /ntsb/api-key --type SecureString --value "$(pass show api/ntsb | head -n1)" --profile ntsb --region eu-west-2
```

and it works — but for the moment `aws` runs, the key sits in that command's own argument
list, which (on a machine with more than one user, or any tool that samples the process table)
is visible via `ps`. This project's standing rule is that a key never reaches a printed line or
anywhere else it doesn't have to.

**An earlier version of this runbook piped a JSON document into `aws ssm put-parameter
--cli-input-json file:///dev/stdin` to avoid that — it does not work.** Reproduced directly
against `aws-cli` 2.36, with a dummy value and no real credentials: the command fails with
"Invalid JSON received". The AWS CLI's `file://` form reads a real file on disk; a *piped*
`/dev/stdin` is not read the same way, so the JSON never actually reaches the command. The
form below keeps the same property (the key never appears as a command-line argument, and
never touches disk) a different way — it hands the key to Python's own `boto3` library on
`stdin`, inside a one-off `uv run` environment, and lets `boto3` make the API call directly,
bypassing the `aws` CLI's own argument parsing entirely:

```
cd <checkout>
pass show api/ntsb | head -n1 | uv run --extra aws --with awscrt python -c '
import sys, boto3
value = sys.stdin.readline().rstrip("\n")
if not value:
    sys.exit("no key on stdin")
ssm = boto3.Session(profile_name="ntsb").client("ssm", region_name="eu-west-2")
ssm.put_parameter(Name="/ntsb/api-key", Type="SecureString", Value=value, Overwrite=False)
print("stored /ntsb/api-key")
'
```

(`<checkout>` — "A note on paths" above.) `--extra aws` pulls in `boto3` (this checkout's
optional AWS dependency group — needed anyway for stage 8's report). `--with awscrt` adds one
more package for this one run only, without changing this project's own dependencies: the
`ntsb` profile authenticates through `aws login`'s newer credential provider, and `boto3` needs
the separate `awscrt` package to read credentials from it — the `aws` CLI already bundles the
equivalent support, which is why the CLI form above does not need it but `boto3` does.

**What this does.** Reads the key from your password store, and calls Parameter Store's
`PutParameter` API directly through `boto3`, storing it as an encrypted (`SecureString`)
parameter named `/ntsb/api-key`. `print("stored /ntsb/api-key")` is the only thing that ever
prints — never the key itself.

**What it costs.** Nothing; a standard parameter is free.

**How to check.**

```
aws ssm describe-parameters --profile ntsb --region eu-west-2 --query "Parameters[?Name=='/ntsb/api-key']"
```

Expect one entry, `"Type": "SecureString"`. (Reading the value back would defeat the point —
this only confirms the parameter exists.)

**If you ever need to replace the key** (rotation), change `Overwrite=False` to
`Overwrite=True` in the command above; `put_parameter` refuses to overwrite an existing
parameter otherwise.

---

## Stage 4 — Deploy the stack

> **Stages 4, 5 and 6 are one sitting, not three separate errands — start stage 4 only when
> you have time to also finish 5 and 6 before the next 03:00 UTC.**
>
> The 03:00 UTC schedule goes live the moment this stage's `cdk deploy` finishes. Until stage 6
> replaces the store with the bridge's real data, every scheduled run writes into (and reads
> from) an **empty** bucket — meanwhile the bridge (still running on your Mac) is doing the
> real work. That is two recorders polling the NTSB sites every night, doubling the load for no
> reason, and each cloud night's empty-store run is thrown away the moment stage 6 finally
> uploads over it. Fixed in this round from an earlier version of this runbook, which put the
> CI hand-over (now stage 9) between stages 5 and 6 — that let the cloud schedule run for days
> on an empty store beside a still-live bridge, which is exactly the situation this box exists
> to prevent.
>
> **If you genuinely cannot finish all three before 03:00 UTC**, say so to yourself plainly:
> every cloud night between stage 4 and stage 6 runs against an empty store and its output is
> discarded, not merged, the moment stage 6's upload replaces the file wholesale; nothing from
> the bridge's own recording is lost, since the bridge keeps running for real until you
> deliberately stop it in stage 6, step 1.

### 4a — Check for an existing GitHub OIDC provider first

An AWS account can hold only **one** IAM **OIDC provider** per identity provider URL. Check
whether one already exists for GitHub Actions before deploying, so the stack imports it instead
of trying to create a duplicate (which CloudFormation would reject):

```
aws iam list-open-id-connect-providers --profile ntsb --region eu-west-2
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
NtsbRecorderStack --profile ntsb --region eu-west-2 --query 'Stacks[0].Outputs' --no-cli-pager`.)

**What it costs.** Nothing extra to deploy the stack itself (CloudFormation is free); the
resources it creates start billing once they exist — see "What it costs", below, for the
running total.

**How to check.**

```
aws cloudformation describe-stacks --stack-name NtsbRecorderStack --profile ntsb --region eu-west-2 --query 'Stacks[0].StackStatus'
```

Expect `"CREATE_COMPLETE"` (or `"UPDATE_COMPLETE"` on a later re-deploy). Now go straight on to
stage 5 — see the box above.

---

## Stage 5 — Upload the first image by hand

*This stage exists because of a decision Andy made on 2026-09-23, logged as a Deviation.* CI's
`image-push` job (`.github/workflows/ci.yml`) only runs on a push to `main`, and this whole
stage only merges to `main` once its own done-criteria are met (spec §14 item 4 — one AWS
night's own log, which is stage 8, has to happen first) — so the very first image has to reach
ECR another way, or the schedule (live since stage 4) runs against an empty registry.

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
not optional, from an Apple Silicon Mac. The commands below default to the S2.5 worktree path
(this stage's own checkout, "A note on paths" above) — use the main checkout path instead once
this pull request has merged:

```
checkout=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/.claude/worktrees/s25-recorder
short_sha=$(git -C "$checkout" rev-parse --short HEAD)
docker build --platform linux/amd64 \
  --build-arg COMMIT_SHA="$short_sha" \
  -t <RepositoryUri>:latest \
  -t <RepositoryUri>:"$short_sha" \
  "$checkout"
```

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
Now go straight on to stage 6 — see the box at the top of stage 4.

**Until this stage's pull request merges to `main`, any further code change needs this whole
stage repeated by hand.** CI is not pushing yet — that only starts at stage 9, deliberately
placed after the merge, not before it.

---

## Stage 6 — Move the bridge's data to AWS

**Read this before deciding what to skip — it is not all-or-nothing.** This stage's steps 1 and
2 are about the `launchd` bridge specifically (stopping it, checkpointing *its* file); steps 3
and 4 are about moving whatever local store exists, from wherever it came from, to AWS. The two
halves skip independently:

- **If the `launchd` bridge never ran, skip steps 1 and 2** — there is nothing to stop or
  checkpoint.
- **If a local store exists at `data/recorder.sqlite` at all** — written by the bridge, by
  `make record` run by hand, or by a container run on your own Mac — **do steps 3 and 4**, so
  the cloud run continues from it rather than starting empty. This is the situation a night-1
  local container run leaves you in: no bridge to stop, but a real store to move.
- **Skip this whole stage only if no local store exists at `data/recorder.sqlite` at all.** The
  first cloud night then finds an empty bucket and does a normal first night (the walk-back
  `recorder/window.py`'s `first_run_window` runs, the same as any brand-new store) — there is
  genuinely nothing to move.

The bridge (`docs/runbooks/recorder-bridge.md`), when it has run, writes to that same
**local** SQLite file. Move whatever is there to AWS now, in this order, so the cloud run
continues from where local recording left off rather than starting from an empty store.

**Never run this stage, or stage 7, between 03:00 and about 05:31 UTC.** That window is the
scheduled task's own possible run time — not just "03:00 for 90 minutes": the schedule retries
a failed *invocation* up to twice within an hour (`infra/recorder_stack.py`'s
`RetryPolicy`), so a task can still *start* as late as roughly 04:00 UTC, and from there it can
run the full 90-minute limit plus the 60-second kill grace the `timeout` wrapper allows —
03:00 + up to 1 hour (last possible start) + 90 minutes + 60 seconds ≈ 05:31 UTC. A manual
upload racing against the scheduled task's own download/upload of the same object is exactly
the "two writers" situation the whole design avoids elsewhere. Pick any other time.

**1. Skip this step if the `launchd` bridge never ran.** Otherwise, check the bridge is not
mid-run, then stop it, so nothing on the Mac writes to the local file again. The bridge fires
at 03:00 **local** time (not UTC — see
`docs/runbooks/recorder-bridge.md` for why local time shifts against UTC across the year), so
this check is against the Mac's own clock, not the cloud schedule's UTC window above:

```
launchctl print gui/$(id -u)/dev.floyda.ntsb-record | grep state
tail -1 /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/recorder.log
```

The first command must print `state = waiting` (not `running`); the second must end with a
`run done ...` line, not a bare `run start` with nothing after it. If either says the bridge is
still running, wait for it to finish before continuing — stopping it mid-run risks the exact
half-written night the store's own transaction boundaries are designed to prevent from ever
being READ as a finished one, but a `bootout` mid-run still kills the process outright rather
than letting it reach its own clean exit. Once both checks agree the bridge is idle:

```
launchctl bootout gui/$(id -u)/dev.floyda.ntsb-record
```

**2. Also skip this step if the `launchd` bridge never ran.** A one-off local run (`make
record`, or a container run) closes its own store cleanly on exit (`Store.close()` always
checkpoints), so there is nothing left over to check. The bridge is the one repeatedly-invoked
writer whose *most recent* run might have been interrupted rather than exited cleanly, which is
what this step guards against — check for an unflushed write-ahead log. SQLite (`store/db.py`)
opens every store in WAL mode, which can leave recent writes sitting in a separate `-wal` file
rather than in the main file — a plain `cp`/`s3 cp` of the main file alone could then miss
them:

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
  s3://<BucketName from stage 4>/recorder.sqlite --profile ntsb --region eu-west-2
```

**4. Verify the upload is byte-for-byte complete** — do not trust a silent success alone:

```
aws s3api head-object --bucket <BucketName> --key recorder.sqlite --profile ntsb --region eu-west-2 --query ContentLength --output text
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

## Stage 7 — Run one task by hand

Before trusting the 03:00 schedule, run the task once yourself and read its log. **Never start
this outside stage 6's own window warning above (03:00–05:31 UTC excluded)** — a manual run
racing the scheduled task would be two writers to the same store, exactly as stage 6 warns.

**1. Read the subnets and security group straight from the stack's outputs** — the cluster and
task family are both named `ntsb-recorder` (fixed in the stack), but the subnets and security
group are generated, so pull them rather than retyping stage 4's terminal output by hand:

```
subnets=$(aws cloudformation describe-stacks --stack-name NtsbRecorderStack --region eu-west-2 --profile ntsb \
  --query "Stacks[0].Outputs[?OutputKey=='SubnetIds'].OutputValue" --output text)
sg=$(aws cloudformation describe-stacks --stack-name NtsbRecorderStack --region eu-west-2 --profile ntsb \
  --query "Stacks[0].Outputs[?OutputKey=='SecurityGroupId'].OutputValue" --output text)
echo "subnets=$subnets"
echo "sg=$sg"
```

**Stop here if either line prints empty.** An empty value means stage 4's deploy has not
actually finished, or you are pointed at the wrong stack — `run-task` below would otherwise
fail with a confusing network-configuration error rather than a clear one.

**2. Start the task, capturing its ARN directly:**

```
task=$(aws ecs run-task \
  --cluster ntsb-recorder \
  --task-definition ntsb-recorder \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$sg],assignPublicIp=ENABLED}" \
  --region eu-west-2 --profile ntsb --no-cli-pager --query 'tasks[0].taskArn' --output text)
echo "$task"
```

**What this does.** Starts the container once, immediately, outside the 03:00 schedule — the
same image, same command, same 90-minute limit as a real night. `$task` holds the started
task's ARN for the next command.

**What it costs.** A few cents at most — Fargate bills by the second while the task runs (see
"What it costs" below). **This is not a quick task**: every night polls every watched docket
(about 940 of them) at the enforced 2-second-per-request floor, so a full run takes roughly
40–50 minutes, not "a few minutes" — the measured first cloud run took 39 minutes. Budget for
that before starting it.

**How to check.** Three ways, from quickest to most detailed:

1. **Watch it live, in your terminal, as it runs:**

   ```
   aws logs tail /ecs/ntsb-recorder --follow --since 1h --region eu-west-2 --profile ntsb \
     --filter-pattern '?"step=" ?"run done" ?"failed=" ?ERROR'
   ```

   The filter keeps this readable across a ~40-minute run by showing only step boundaries, the
   final summary, failure counts and errors — not every one of the roughly 940 per-case lines.
   `Ctrl-C` stops watching without stopping the task.

2. **The task's own status, including why it stopped:**

   ```
   aws ecs describe-tasks --cluster ntsb-recorder --tasks "$task" \
     --region eu-west-2 --profile ntsb --no-cli-pager --query 'tasks[0].[lastStatus,stoppedReason,containers[0].exitCode]'
   ```

   Poll until `lastStatus` reads `"STOPPED"`. `exitCode` of `0` is success. **`stoppedReason` is
   the field that explains a failure that leaves no log at all** — an image the task could not
   pull (a typo in the tag, or stage 5 not actually done yet) or a secret it could not read
   (Parameter Store) both stop the task before it ever starts logging, and only `stoppedReason`
   says which.

3. **The full log, in the CloudWatch console** (region **Europe (London), `eu-west-2`** — the
   region selector is in the console's top-right corner; "Console access", above, has the exact
   path): CloudWatch → Log groups → `/ecs/ntsb-recorder` → the one log stream (named
   `recorder/recorder/<task id>`). Expect one line per case, ending with a `run done` summary
   line (spec S9.1's format: `run done cases=N changed=N new_docs=N failed=N ... minutes=N`).
   No case text ever appears in the log (spec S9.1) — only counts and outcomes.

---

## Stage 8 — Confirm the first scheduled run

The 03:00 UTC schedule is now the only thing that should ever write to the store. The morning
after the first 03:00 UTC has passed:

```
aws logs tail /ecs/ntsb-recorder --since 24h --region eu-west-2 --profile ntsb
```

**What this does.** Prints the last 24 hours of the recorder's log lines directly in your
terminal — the same content stage 7 read from the console, without opening a browser.

**How to check.** A `run done` line with today's date, and no `failed=` count higher than a
handful of cases (some failures — a docket temporarily unreachable, a malformed PDF — are
normal and already counted; a large number is not). **Nothing alerts you if a night is
missed entirely** (no task started, so no failure to alert on either) — check the log
yourself after the first few nights, until the pattern is familiar.

**This log is spec §14 item 4's own done-criterion — the last thing needed before this
pull request can merge.**

---

### Running the counts-only report against the AWS store

`scripts/recorder_report.py` already reads an `s3://` `NTSB_STORE` — nothing here needed
changing; this is where reading it from your own machine is written down. It pulls the S3
object to a temporary file under `NTSB_DATA_DIR` (never opening or writing the S3 object
itself) and opens that copy strictly read-only, the same as it does for a local file.

```
uv sync --extra aws
AWS_PROFILE=ntsb NTSB_STORE=s3://<BucketName from stage 4>/recorder.sqlite \
  uv run --with awscrt python -m scripts.recorder_report
```

**What this does.** `uv sync --extra aws` installs `boto3` (not part of the default install,
since only this S3 path needs it — `store/sync.py`) into this checkout's own environment, for
good. `--with awscrt` on the run itself adds one more package, for this one run only, for the
same reason stage 3 needs it: the `ntsb` profile authenticates through `aws login`'s newer
credential provider, which `boto3` needs `awscrt` to read. The command downloads the current
store and prints the same counts-only report `make recorder-report` prints against a local
file: run summaries, arrival percentiles, the change-feed comparison, regulation transitions,
the closure tail, suspected re-numbers. Add `--out docs/results/s25-recorder-report.txt` to
also save it.

**What it costs.** A few cents at most for the download (the same order as stage 6's upload).

**How to check.** The report's own "nights recorded" and "distinct finished nights" lines
should match what stage 8's CloudWatch log shows has actually run.

---

## Stage 9 — After this stage's pull request merges

Everything through stage 8 above happens **before** the merge, on purpose — stage 5's manual
upload exists precisely because CI cannot push before it either, and merging any earlier would
mean merging without the one AWS night's log spec §14 item 4 requires. Once the pull request
has actually merged (through this project's normal review process, not a step in this
runbook), do this once:

```
gh variable set AWS_DEPLOY_ROLE_ARN --body <DeployRoleArn from stage 4>
```

**What this does.** Sets a GitHub Actions repository variable (not a secret — the role ARN
identifies the role but grants nothing on its own; only a workflow run in *this* repository, on
`main`, can assume it, per the trust condition `infra/recorder_stack.py` sets). Deliberately
done *after* the merge, not before: setting it earlier would let the merge commit itself
trigger CI's first automatic push, before stages 6–8 have actually proven the manually-uploaded
image and the moved store work together.

**What it costs.** Nothing.

**How to check.**

```
gh variable list
```

Expect `AWS_DEPLOY_ROLE_ARN` in the list. `.github/workflows/ci.yml`'s `image-push` job runs on
every push to `main`; once the variable is set, it stops skipping and builds and pushes
`ntsb-recorder:latest` (and a tag matching the commit's short SHA) to ECR on every future
merge, from this point on — check the run in the "Actions" tab of the repository on the next
merge that touches this project, and confirm the `image-push` job succeeds rather than being
skipped.

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

**If you plan to redeploy afterwards, read this first — it is not automatic, and it is not
just `cdk deploy` again.**

The ECR repository and the log group keep the **same fixed name** every time
(`ntsb-recorder`, `/ecs/ntsb-recorder`) — that is deliberate (it is what lets stage 7's manual
run and CI's `image-push` refer to them by name instead of looking them up). It also means a
fresh `cdk deploy` after a `cdk destroy` tries to *create* a repository and a log group with
names that **already exist** (the retained, now-orphaned ones from before) and fails. The
practical, low-stakes recovery — appropriate here because the retained data in both is
disposable (ECR only ever keeps the newest 5 images anyway, all rebuildable from git history and
a fresh CI push; CloudWatch log lines are 30 days of operational output, not a record this
project keeps) — is to delete the two orphans first, then redeploy (add
`-c github_oidc_provider_arn=<arn>` again if stage 4a needed it the first time — an existing
OIDC provider is untouched by `cdk destroy`, since it is not one of the three RETAIN resources
and CDK never deletes something it does not own, so the same import is needed again):

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
it. **Before trusting the schedule again, copy the store across, the same way stage 6 first
moved it from the bridge:**

```
aws s3 ls --profile ntsb --region eu-west-2 | grep -i ntsbrecorderstack   # find the OLD, orphaned bucket's name
aws s3 cp s3://<old bucket>/recorder.sqlite s3://<new BucketName from the fresh deploy's output>/recorder.sqlite --profile ntsb --region eu-west-2
```

Verify with the same `head-object`/`stat` comparison stage 6 uses.

**The new ECR repository is also empty, even though its name survived.** A repository's name
being retained does not retain its images — those were deleted along with the repository
itself in the recovery command above. **Repeat stage 5 (upload the image by hand) before
trusting the schedule**, exactly as the first deploy needed it, for the same reason: nothing
has pushed to the new repository yet, and a run before an image exists fails with no log line.
Do the store copy and the image upload both before the next 03:00 UTC, for the same reason the
box at the top of stage 4 gives for the very first deploy.

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
becomes one each time `run-task` (by hand, stage 7) or the schedule (stage 8) starts it.

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
