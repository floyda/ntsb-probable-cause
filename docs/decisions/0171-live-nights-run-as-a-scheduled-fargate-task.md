# 0171 — Live nights run as a scheduled Fargate task, from a pinned image; the Mac is retired

From the S4 design session with Andy, 2026-10-10. Replaces
[0158](0158-live-runs-on-the-mac-at-the-batch-price.md) item 1 (the Mac) and
[0166](0166-a-read-only-aws-key-for-the-live-shadow.md) (the Mac's read-only key). Detail: the
S4 specification, §4.

## Context

1. **S3.3 ran on Andy's Mac**, which must be awake and needs a read-only AWS key (0166). 0158 left
   the service to S4.
2. **The recorder already runs as a scheduled Fargate task** (`NtsbRecorderStack`), from 03:00 UTC,
   its last retry ending by about 05:31 UTC.
3. **A night of 30 cases takes about 45 minutes** (estimate), past Lambda's 15-minute limit. A
   public repository's GitHub Actions logs are public.
4. **The recorder's image repository keeps only its 5 newest images.**
5. **The recorder's cloud runs only merged code**: CI builds its image only on a push to `main`
   (0158, context 1). S4's closing rule needs cloud nights before S4 merges (decision 0181).

## Decision

1. **A new stack, `NtsbLiveStack`**, beside the recorder's, which is unchanged: its own VPC with no
   NAT gateway, its own image repository `ntsb-live` with immutable tags, a Fargate task (x86, 0.5
   vCPU, 1 GB) started by EventBridge Scheduler at 06:00 UTC with a 3-hour limit, a task role that
   can never delete, and the live OpenRouter key in Parameter Store (a SecureString Andy writes).
   The schedule is deployed disabled; enabling it is the go-ahead.
2. **The image is built from a clean commit** by `scripts/build_live_image.sh`, tagged
   `live-<commit>`, never `latest`, and pinned by digest. During S4 it is built from S4 branch
   commits, kept reachable by the merge commit
   ([0033](0033-stage-pull-requests-keep-their-commits.md)); after the merge, from `main`.
3. **The task enforces what `paid_run.sh` enforces**: locked dependencies, a recorded commit, a clean
   tree, the version 1 check, the caps.
4. **Andy runs `cdk deploy`** and every IAM create or delete. Claude asks Andy before the first
   cloud night, with its cost and duration.
5. **The Mac is retired** after the first good cloud night: Andy removes `ntsb-live-reader`, its
   key and inline policy, the `pass` entry and the `ntsb-live` profile; `ntsb-live run` refuses
   outside the image unless `--dry-run`; `live_env.sh` defaults to `ntsb`; `make s33-morning` goes.

## Why

1. **Unattended is the done means.** A Mac that sleeps cannot meet it.
2. **Known parts**: the recorder proved the network, logging and key handling. About $0.15 a month
   (estimate, from the AWS price list for eu-west-2, read 2026-10-10).
3. **Its own network and repository keep the stacks independent**: a VPC without NAT is free, and
   live images cannot expire the recorder's.
4. **A digest-pinned image** means the night runs exactly the commit that was reviewed.
5. **Branch images are a knowing exception to merged-only code**, limited to S4's own nights: the
   build script refuses a dirty tree, the tag names the commit, and the merge commit keeps it
   reachable. After the merge the task returns to images built from `main`.

## What this rules out

- **Lambda.** Cheaper idle. Rejected: the 15-minute limit.
- **GitHub Actions on a schedule.** No AWS task to build. Rejected: public logs, and the key would
  live in the repository's secrets.
- **Sharing the recorder's network and repository.** Fewer resources. Rejected: it changes the
  recorder's template, and the shared image rule could expire the recorder's image.
- **Keeping the Mac as a fallback.** Rejected: two places that can spend, and a key to keep.

## Status

Accepted, 2026-10-10 (Andy: "A" on the cloud run, the first cloud night and the Mac's retirement).
