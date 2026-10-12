# Runbook — Live cloud nights

*For S4. Specification: `docs/specs/2026-10-10-s4-predictions-and-resolution-design.md`
(sections 4, 5, 7, 8, 11 and 15). Decisions: 0168 to 0183. This replaces
`docs/runbooks/live-shadow-mornings.md`, which stays as the record of S3.3.*

**What this is.** Once a night, at 06:00 UTC, a small cloud computer (an AWS Fargate **task**)
starts by itself. It takes the cases the NTSB has closed, reads their documents, lets the agent
(Ellery, version 1) write a verdict for each, and saves the result in a private **bucket**. Later,
when the NTSB's own codes arrive, it scores the verdict. You do not run anything on your Mac
for this to work. Most nights you do nothing.

This runbook has two jobs. Sections 1 to 6 tell you what each email, message and situation
means, and what you do (usually nothing). Sections 7 to 11 are the steps you follow once: to
deploy, to start, to check, and to retire the old Mac key.

Words in **bold** the first time they appear are in the glossary at the end. Every AWS command
here uses `--profile ntsb` and `--region eu-west-2`. Run `aws login` first (a sign-in lasts a
few hours). No command here prints a key.

---

## 1. What a night does

1. **06:00 UTC.** The schedule starts the task.
2. The task writes a **marker** (`nights/<date>/started`). A second task on the same day sees the
   marker and stops. This is how two tasks never run together.
3. It checks before spending anything: the image is version 1, the recorder's store is sound, and
   the recorder finished its own run today.
4. It finishes any **unfinished run** it finds in the bucket. Calls already answered are not paid
   for again.
5. It reads how much the live key has spent this month and works out tonight's number of cases
   (section 4).
6. It fetches each case's record and documents, and the agent codes them one at a time. After
   every reply, the run folder is copied to the bucket.
7. It scores earlier cases whose NTSB codes have now arrived (**later scores**).
8. It builds the **export** (the board's data files) and copies it to the bucket.
9. It writes `nights/<date>/night.json` and the night's **manifest**, publishes one **metric**
   (this means "a night finished"), and sends one email per alert kind.
10. A GitHub job adds the new manifests' hashes to the public **ledger**. GitHub runs a
    schedule only from the repository's default branch, so the 10:00 UTC schedule starts only
    after the stage is merged. Until then the job runs when a commit is pushed to the S4 branch
    (section 9, "Run the job before the merge").

Nothing that leaves the task names a case: emails, the ledger and the log hold kinds, counts,
dates and hashes.

## 2. What you do each day

Usually nothing. An email arrives only when something needs attention (section 3), or when the
alarm changes state. To look at the state yourself, from the project folder with
`NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data` set:

```
make s4-export          # copies the bucket to data/live-mirror, builds data/live-export,
                        # and copies the night's own export to data/live-night-export
make s4-verify-ledger   # checks the copy against the public ledger
make s4-report          # writes docs/results/s4-live.txt (counts only)
```

`make s4-spend` shows S4's development spend against its $10 line. It does not show the live
key's spend; that is in the report, and on OpenRouter's key page.

To read the task's log of the last day:

```
aws logs tail /ecs/ntsb-live --since 24h --region eu-west-2 --profile ntsb
```

The log can name a case. Do not paste it into a chat or a public place.

## 3. The emails and what to do

One email per alert kind per night. The subject names the kind; the body holds counts only.
"Nothing was spent" means the night stopped before any model call.

| Kind | What it means | What you do |
|---|---|---|
| `version-refused` | The image's agent text or settings are not version 1's. Nothing was spent. | Do not deploy anything else. Tell Claude. Every night stops the same way until the right image runs. |
| `docket-folders` | The live document folder is set to the development one, or inside it. Nothing was spent. | Tell Claude. It is a setting in the image. |
| `resume-refused` | An unfinished run began on another image, so this image will not finish it. Nothing was spent. | See section 5, "resume-refused". |
| `docket-changed` | An unfinished run was to be resumed, but at least one of its cases' documents, read again from the NTSB, are not the files the run first read (their hashes differ from the run's `dockets.json`). The run was not resumed, so no case is coded from documents it was not first shown. Nothing was spent. | Tell Claude. Every night stops the same way while the files differ. Do not delete anything in the bucket. |
| `resume-failed` | An unfinished run could not be resumed, or a finished run's records could not be completed, because its folder is not as the code expects (for example a file is missing). Nothing was spent tonight. The later scores, the export and the night record still ran. | Tell Claude the alert kind. Every night stops the same way until the folder is put right. Do not edit the run folder. |
| `key-unreachable` | The live OpenRouter key's page could not be read, or answered something unexpected, or the key has no limit. Nothing was spent. | Usually nothing: the next night tries again. If it repeats on 2 nights, open OpenRouter's key page and check that the key exists and has a $10 monthly limit, and that the Parameter Store value is the live key (section 7, step 3). Then tell Claude. |
| `store-unsound` | The recorder's store has a case with no case row or run row, or it was written by newer code than the image's. Nothing was spent. | Usually nothing: the recorder rewrites its store each night. If it repeats on 2 nights, tell Claude. Do not edit the store. |
| `recorder-not-finished` | The recorder had not finished its run for today when the night started. Nothing was spent. Every queued case waits. | Usually nothing. If it repeats on 3 nights, see `docs/runbooks/recorder-bridge.md` and `docs/runbooks/recorder-deploy.md`, and tell Claude. |
| `money-held-back` | The month's money allows fewer cases than are queued. The cases wait. This is normal after a busy night. | Nothing. The queue drains when the key's limit resets at the start of the month. If the queue grows for a week, tell Claude. Raising the limit is your decision, on OpenRouter. |
| `budget-guard` | The code's own monthly guard would have been passed. It should never happen in the cloud. | Tell Claude. |
| `fetch-failed` | A case's record or document list could not be read from the NTSB, during a resume or a completion. Not tied to one case in the email. | Nothing. The next night tries again. If it repeats for a week, tell Claude. |
| `outage` | Every fetch failed tonight: the NTSB's site is down or unreachable. It counts against no case. | Nothing. |
| `unreachable-3` | A case has failed to fetch on 3 nights when other cases fetched. | Nothing yet. |
| `unreachable-final` | A case failed on 7 such nights. It is settled as "not coded: unreachable", and that is final. | Nothing. It shows on the board as not coded. |
| `awaiting-codes-7` | At least one coded case has waited 7 nights or more for the NTSB's codes. | Nothing. It repeats every night while any case waits this long. This is expected. If it persists for weeks, tell Claude. |
| `later-score-failed` | One or more later scores could not be made. The body counts them by error class. The others went on. | Nothing at first: the next night tries again. If the same count persists for a week, tell Claude. |
| `export-failed` | The export could not be built or copied. The night still finished. | Nothing. The next night rebuilds the whole export. See section 5, "The export is not one step". |
| `night-crashed` | An unexpected error stopped the task. No counts. | Read the end of the log (section 2) for the error's name. Work done before the crash is in the bucket. Tell Claude the error name, not the log. See also section 5, "A failed night after the day's marker". |

**The missed-night alarm.** CloudWatch watches the metric of step 9 in section 1. If no night finished for 30
hours, it sends an email called `ALARM`. A task that never started or crashed is caught this
way too. When a night finishes again, it sends an `OK` email. Two facts: after a fresh deploy
the alarm sits in `ALARM` until the first finished night, which then sends the `OK` email; and
an alarm that is already in `ALARM` sends nothing for a new problem. What you do: read the last
night's email and log (section 2), then tell Claude.

## 4. Money

- Live runs use their own OpenRouter key, with a **$10 a month** limit that you set on OpenRouter,
  reset monthly. The development key and its $40 guard are separate.
- A night codes at most `floor((cap - spent this month) / $0.30)` cases. The cap is $9, or the
  key's limit less $1 if that is lower. Every case could run to its $0.30 limit, so no night can
  pass the key's limit.
- A case costs about $0.005 billed. A month of 100 closures costs about $0.51.
- If the key page cannot be read, or the key has no limit, the night refuses (`key-unreachable`).
- The report (`make s4-report`) gives the live key's spend in the first cloud nights apart from
  later nights. It counts from each night's run records, so a call that never reached a record is
  not in it.

## 5. Situations

**`resume-refused`.** A night was killed (the 3-hour limit, or AWS stopped the task) while a run
was unfinished. A run is finished only on the image that started it, because the code that
makes the run must not change in the middle of it. So tonight's image refused, and nothing was
spent. What you do:

1. Do not deploy a new image while a run is unfinished. An unfinished run is a folder under
   `runs/` in the bucket that has no `run.jsonl`, or whose `run.jsonl` has no `finished` time
   (and whose `spec.json` says `"sample": "live"`).
   `aws s3 ls s3://<bucket>/runs/<run id>/ --profile ntsb --region eu-west-2` lists a folder.
   The bucket name is the output `LiveBucketName` of the stack (section 7, step 1). The run id is
   in the log line (section 2).
2. To finish it, run the image that started it. **Verify on first use.** A deploy replaces the
   task definition and deregisters the older revision, so there is no older revision to run.
   Instead, deploy `NtsbLiveStack` again with the full context (section 7) and
   `-c live_image_digest=<the digest that started the run>`. ECR keeps the 5 newest images, so
   that image is still there. Find the digest: the run's `spec.json` in the bucket names its
   commit, and the image tag is `live-<commit>`:
   ```
   aws s3 cp s3://<bucket>/runs/<run id>/spec.json - --profile ntsb --region eu-west-2
   aws ecr describe-images --repository-name ntsb-live --image-ids imageTag=live-<commit> --profile ntsb --region eu-west-2 --query "imageDetails[0].imageDigest" --output text
   ```
   (`spec.json` holds the commit, which is the tag's suffix, and no case text.) Keep `-c live_schedule=enabled` in that deploy if the schedule
   is on. Let the next night finish the run.
3. Once it has finished, deploy again with the new digest (full context). The nights after that
   run on the current image.

**A failed night after the day's marker.** The marker `nights/<date>/started` exists, and the task
cannot delete it. So a second task the same day stops at once. If the night failed early and you
want it to run again that day, delete the marker yourself, then start a task by hand:

```
aws s3 rm s3://<bucket>/nights/<date>/started --profile ntsb --region eu-west-2
```

**Verify on first use:** that the task can start again after you delete the marker (the task writes the
marker with a conditional put, and the delete may leave a delete marker in a versioned bucket). If
the new task still stops with "a night already started today", tell Claude.

Then follow section 8, "Start a task by hand". If you do nothing, the next night runs as normal.

**A kill before the first `spec.json` upload.** It leaves a folder in `runs/` that is not a live run:
it holds inputs and the backfill list, and is never resumed. The next night makes the backfill
list again. Nothing was coded and nothing was paid. You do nothing.

**The export is not one step.** The export is many files, copied one at a time. A failure part-way
leaves a mixed `export/board-1/` folder in the bucket and the alert `export-failed`. The next
night rewrites the whole export. The site must not treat any one file as proof that the export
is complete.

**`ntsb-live export`** (and `make s4-export`) runs on your Mac, because it needs the repository's
`.git` for the commit stamp. The night builds its own export inside the task.

**Names that survive the fixed names.** The image repository `ntsb-live`, the log group
`/ecs/ntsb-live` and the live bucket are kept if the stack is deleted (`RETAIN`). To create the
stack again, remove them first or import them, or the deploy fails because the names exist.

**Every `cdk deploy` needs the full context.** CDK does not remember the `-c` values from the
last deploy. A deploy without `-c live_schedule=enabled` switches the schedule off again. A
deploy without `-c ledger_branches=main` brings back the S4 branch's trust. So every command in
sections 7 to 11 is written out in full. Copy it whole.

## 6. Messages `ntsb-live` prints

You see these only when you run `make s4-dry-run`, or when you read the log. The first column
quotes the program's own text. A test checks that each quoted text is in the program.

| What you see | What it means | What you do |
|---|---|---|
| `a night already started today: this task stops here and does nothing else` | The day's marker already existed. A second task stopped. | Nothing. If you started it by hand to rerun a failed night, delete the marker first (section 5). |
| `the export failed (` | The export step failed; the class name follows. The night goes on. | See `export-failed` in section 3. |
| `night stopped:` | The night ended at a check or a refusal; the kind follows. | Find the kind in section 3. |
| `later scores:` | How many earlier cases were scored tonight. | Nothing. |
| `alert:` | An alert kind the night raised. | Find the kind in section 3. |
| `paid nights run only in the live image (decision 0171)` | `ntsb-live run` was started without `--dry-run` outside the image. | Nothing was done. Use `make s4-dry-run` on the Mac. Paid nights run only in the cloud. |
| `NTSB_LIVE_ALERT_TOPIC_ARN is not set` | The task has no alert topic. | Tell Claude. It is a stack setting. |
| `the live night's runs folder must be the bucket mirror's runs/ folder` | A code fault in how the task was built. | Tell Claude. The day is not claimed, so a corrected task can still run today. |
| `the key endpoint could not be reached` | OpenRouter's key page did not answer. The reason class follows. | See `key-unreachable`. |
| `the key endpoint answered` | The key page answered with an error code. | See `key-unreachable`. |
| `the key endpoint's answer has no data object` | The key page answered in an unexpected shape. | See `key-unreachable`. |
| `the key's monthly usage is not a valid number` | The key page's spend field is wrong. | See `key-unreachable`. |
| `the key's limit is not a valid number` | The key has no limit, or an unreadable one. | Set a $10 monthly limit on the key on OpenRouter. See `key-unreachable`. |
| `the agent's prompt version is` | The agent's text is not version 1's. | See `version-refused`. |
| `these settings are not version 1's` | A setting that changes what Ellery receives is not version 1's. | See `version-refused`. |
| `live_docket_dir must differ from docket_dir` | The two document folders are the same or nested. | See `docket-folders`. |
| `began at commit` and `a run is resumed only` | An unfinished run began on another image. | See `resume-refused` and section 5. |
| `the recorder has not finished a run on` | The recorder's store is not today's yet. | See `recorder-not-finished`. |
| `no case row or no run row` | The store is not sound. | See `store-unsound`. |
| `store schema version` | The store was written by newer code than the image's. | See `store-unsound`. |
| `the unfinished run has` and `cases to answer` | An unfinished run needs more money than is left this month. | See `money-held-back`. |
| `money holds back` | A warning: money holds back some queued cases tonight. | See `money-held-back`. |
| `reserved by other runs exceeds the` | The code's monthly guard refused. | See `budget-guard`. |
| `a case's record or docket could not be read` | A fetch or document error. No case is named. | See `fetch-failed`. |
| `AWS error (` | An AWS problem inside the task. The class name says which. | Tell Claude the line. |
| `the AWS login has expired` | On your Mac: the sign-in ended. | Run `aws login`, then run the command again. |
| `another morning is running` | On your Mac: a second dry run holds the lock. | Wait for it. A lock does not survive a restart. |
| `information: this dry run does not check` | The dry run cannot tell whether an unfinished run began on another image. This is expected on the Mac. | Nothing. Only the cloud night can check it. |
| `cases queued; a morning would code` and `no model was called and no run folder was written` | The dry run's lines: how many cases are queued, how many a night would code, and one fetch. | Read them (section 10, step 1). |
| `is resumed with no backfill held anywhere` | The folder of an unfinished run lacks its backfill list. | Do not delete it. Tell Claude. |
| `resumed with the records it began with` | The folder of an unfinished run lacks the file that holds its cases. | Do not delete it. Tell Claude. |
| `no recorded training cut-off for` | The model has no recorded training cut-off date. | Tell Claude. |
| `live run folders appeared during the run` | Two live run folders were made during one night. | Do not delete anything. Tell Claude. |
| `NTSB_API_KEY is not set` | On your Mac: the NTSB key was not read. | Use `make s4-dry-run`; check that the `pass` entry `api/ntsb` exists. |
| `OPENROUTER_API_KEY is not set` | On your Mac: the live key was not read. | Check that the `pass` entry `api/openrouter-live` exists. |
| `AWS login expired: run 'aws login'` | `scripts/live_env.sh` could not read the live stack because the sign-in ended. It prints no settings. | Run `aws login`, then run the command again. |
| `profile could not read the stack` | `scripts/live_env.sh` could not read a stack's output. | Run `aws login`, and check that the `ntsb` profile exists (`aws configure list-profiles`). AWS's own error follows the line. |
| `has no --resume option` | A batch run was cancelled. Live runs are not batches, so this should not appear. | Tell Claude. |

---

## 7. Deploy: the first time

Do these in order. **Claude asks you before the first cloud night** (section 10) and states its
cost and length. Until then the schedule stays off.

**Values you need.** You get each from AWS, once.

- `<recorder bucket>`: the recorder's bucket name.
  ```
  aws cloudformation describe-stacks --stack-name NtsbRecorderStack --profile ntsb --region eu-west-2 --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text
  ```
- `<alert email>`: the address that receives the alerts.
- `<provider arn>`: the GitHub **OIDC provider** of the account, if it exists. An account can hold
  only one. Check:
  ```
  aws iam list-open-id-connect-providers --profile ntsb --region eu-west-2
  ```
  Use the entry whose ARN ends in `oidc-provider/token.actions.githubusercontent.com` (the
  recorder's stack may have made it). If the list is empty, tell Claude before going on.
- `<digest>`: the image's digest, printed by step 4. Step 1 uses the placeholder instead.

**Step 1: deploy the stack with the schedule off and a placeholder image.** From the `infra`
folder (`cd infra`). The stack needs a one-time `cdk bootstrap` of the account, which the recorder
already did.

```
cdk deploy NtsbLiveStack --profile ntsb -c recorder_bucket=<recorder bucket> -c alert_email=<alert email> -c github_oidc_provider_arn=<provider arn> -c live_image_digest_placeholder=1 -c ledger_branches=main,s4-predictions-and-resolution
```

CDK lists the IAM changes (two roles for the task, one for the schedule, one for the ledger job)
and asks you to confirm. It makes the live bucket, the image repository `ntsb-live`, the alert
topic, the alarm, the log group `/ecs/ntsb-live` and the schedule, switched off. When it ends,
note the outputs: `LiveBucketName`, `RepositoryUri`, `AlertTopicArn`, `LedgerRoleArn` and
`LogGroupName`. You can read them again at any time:

```
aws cloudformation describe-stacks --stack-name NtsbLiveStack --profile ntsb --region eu-west-2 --query "Stacks[0].Outputs" --output table
```

**Step 2: confirm the alert email.** AWS sends a message called "AWS Notification - Subscription
Confirmation" to `<alert email>`. Open it and choose "Confirm subscription". Until you do, no
alert arrives.

Then send a test alert. `<AlertTopicArn>` is the output `AlertTopicArn` of the stack (step 1;
the `describe-stacks` command there lists it):

```
aws sns publish --topic-arn <AlertTopicArn> --subject "Ellery test" --message "test" --profile ntsb --region eu-west-2
```

An email with the subject "Ellery test" should arrive within a minute. Write today's date as
`alert_email_received` in the attestation file (section 10, step 4).

**Step 3: write the live key.** It lives in your `pass` store as `api/openrouter-live`. This line
sends it straight into AWS **Parameter Store**. The value never appears on the screen:

```
pass show api/openrouter-live | head -n1 | tr -d '\n' | aws ssm put-parameter --name /ntsb/live/openrouter-key --type SecureString --value file:///dev/stdin --overwrite --profile ntsb --region eu-west-2
```

`head -n1` keeps the first line of the `pass` entry only, and `tr -d '\n'` removes its newline.
Without them AWS would store the newline, the `Authorization` header would hold it, and every
night would stop with `key-unreachable`. (The recorder runbook writes its key with a short
Python program because `--cli-input-json file:///dev/stdin` failed there, and to keep the key out
of the argument list; this `--value` form was checked with aws-cli 2.36.44.) The command
prints a version number only. Check what was stored, by name and type, never by value:

```
aws ssm describe-parameters --profile ntsb --region eu-west-2 --parameter-filters Key=Name,Values=/ntsb/live/openrouter-key
```

It must show the name `/ntsb/live/openrouter-key`, the type `SecureString` and a version. On OpenRouter, check the live key has a limit of $10
and that its reset period is **monthly**. The code does not read the reset period (section 10 says
where you confirm it).

**Step 4: build and push the image.** This pushes an image to ECR, so `make` asks for `CONFIRM=yes`. Run
both commands from the project folder (`ntsb-probable-cause`, not `infra`).
Commit first: the script refuses a tree with uncommitted changes. Sign Docker in to ECR (the
password goes through a pipe and is not shown):

```
aws ecr get-login-password --region eu-west-2 --profile ntsb | docker login --username AWS --password-stdin "$(aws cloudformation describe-stacks --stack-name NtsbLiveStack --profile ntsb --region eu-west-2 --query "Stacks[0].Outputs[?OutputKey=='RepositoryUri'].OutputValue" --output text | cut -d/ -f1)"
make s4-image CONFIRM=yes
```

It builds for `linux/amd64`, tags the image `live-<commit>` (never `latest`), pushes it, and prints
one line: the digest, `sha256:` and 64 hexadecimal characters. Tags are **immutable**, so the same
commit cannot be pushed twice with different contents.

**Step 5: deploy again with the real image, schedule still off.** From the `infra` folder. Do this
only when no live run is unfinished (section 5).

```
cdk deploy NtsbLiveStack --profile ntsb -c recorder_bucket=<recorder bucket> -c alert_email=<alert email> -c github_oidc_provider_arn=<provider arn> -c live_image_digest=<digest> -c ledger_branches=main,s4-predictions-and-resolution
```

## 8. Start a task by hand

You need this for section 5 and for a first test. It runs the same command as the schedule.

1. Find the schedule and read its network settings (the stack has no output for them). The
   schedule's logical id in the stack is `Nightly`. **Verify on first use:** the physical id
   should be the schedule's name; if the second command does not accept it, read the name in the
   Amazon EventBridge Scheduler page of the console.
   ```
   aws cloudformation describe-stack-resource --stack-name NtsbLiveStack --logical-resource-id Nightly --profile ntsb --region eu-west-2 --query "StackResourceDetail.PhysicalResourceId" --output text
   aws scheduler get-schedule --name <schedule name> --region eu-west-2 --profile ntsb --query "Target.EcsParameters.NetworkConfiguration.awsvpcConfiguration"
   ```
2. Start the task. Put the subnet ids and the security group id from the last output in place.
   **Verify on first use:** the scheduler's `get-schedule` output has PascalCase members
   (`Subnets`, `SecurityGroups`, `AssignPublicIp`) under the outer key `awsvpcConfiguration`. The
   ECS `run-task` command below needs camelCase (`subnets`, `securityGroups`, `assignPublicIp`).
   The difference is correct: copy the values, not the spelling, and do not "fix" it.
   ```
   aws ecs run-task --cluster ntsb-live --task-definition ntsb-live --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[<subnet ids>],securityGroups=[<security group>],assignPublicIp=ENABLED}" --region eu-west-2 --profile ntsb --no-cli-pager --query "tasks[0].taskArn" --output text
   ```
   `--task-definition ntsb-live` runs the newest revision, which is the only one that exists
   (section 5 says how to finish a run that began on an older image).
3. Follow the log: `aws logs tail /ecs/ntsb-live --follow --since 10m --region eu-west-2 --profile ntsb`.

Never start a task while the 06:00 UTC night is running. The marker stops it, but do not rely on it.

## 9. The ledger on GitHub

The ledger job (`.github/workflows/ledger.yml`) does nothing until the five parts below exist. Set
the variable last.

1. **Two repository secrets** (secrets are masked in public logs; variables are not). These read
   the values from AWS and send them straight to GitHub, so nothing is shown. **Verify on first
   use:** run the inner CloudFormation `describe-stacks` command (the one inside `$(...)`) on its own first and check
   that it prints an ARN (or a bucket name). With an expired login it prints nothing or `None`, and
   `gh secret set --body "$(...)"` would store that empty or `None` value without complaint.
   ```
   gh secret set LEDGER_ROLE_ARN --repo floyda/ntsb-probable-cause --body "$(aws cloudformation describe-stacks --stack-name NtsbLiveStack --profile ntsb --region eu-west-2 --query "Stacks[0].Outputs[?OutputKey=='LedgerRoleArn'].OutputValue" --output text)"
   gh secret set LIVE_BUCKET --repo floyda/ntsb-probable-cause --body "$(aws cloudformation describe-stacks --stack-name NtsbLiveStack --profile ntsb --region eu-west-2 --query "Stacks[0].Outputs[?OutputKey=='LiveBucketName'].OutputValue" --output text)"
   ```
2. **The `ledger` branch**, with an empty `ledger.jsonl`. The job never creates it. Use a fresh
   copy of the repository so nothing in your working folder moves:
   ```
   dir="$(mktemp -d)" && git clone --quiet git@github.com:floyda/ntsb-probable-cause.git "$dir" && git -C "$dir" switch --orphan ledger && : > "$dir/ledger.jsonl" && git -C "$dir" add ledger.jsonl && git -C "$dir" commit --quiet -m "ledger: start" && git -C "$dir" push origin ledger
   ```
3. **Protect the branch**: no force push and no deletion. **Verify on first use** (the `gh api`
   call and its body). `enforce_admins` is `true`, so no administrator, you included, can force-push
   or delete the branch either. This is tamper evidence; it does not block the job's bot, which
   only adds commits. Do **not** add "require a pull request" or a push restriction: the bot
   pushes straight to the branch with the job's own token, and either rule would stop it.
   ```
   gh api --method PUT repos/floyda/ntsb-probable-cause/branches/ledger/protection --input - <<'JSON'
   {"required_status_checks": null, "enforce_admins": true, "required_pull_request_reviews": null, "restrictions": null, "allow_force_pushes": false, "allow_deletions": false}
   JSON
   ```
4. **No GitHub environment.** The job does not use one. An environment changes the sign-in
   identity that the role trusts, and the role would then refuse the job. Do not add one.
5. **Last: enable the job.**
   ```
   gh variable set LEDGER_ENABLED --body true --repo floyda/ntsb-probable-cause
   ```
   Before this variable is `true`, the workflow is a no-op.

**Run the job before the merge.** The workflow file is not on `main` yet, so GitHub will not run
its schedule, and a manual start cannot start it either. Before the merge the job runs on a
push to the S4 branch. After a night has finished, push to the branch (or ask Claude to), for
example from the project folder:

```
git commit --allow-empty -m "ledger: run the job" && git push origin s4-predictions-and-resolution
gh run list --workflow ledger --branch s4-predictions-and-resolution --repo floyda/ntsb-probable-cause
```

Wait until the run shows as completed, then run `make s4-verify-ledger`. After the merge, the
10:00 UTC schedule takes over and the push is not needed. The job's log holds hashes and counts,
never contents.

## 10. Before the first night, and the first night

**Step 1: the dry run.** On your Mac, `pass` unlocked, signed in with `aws login`:

```
make s4-dry-run
```

It reads the live bucket and the recorder's store, reads the live key's spend, fetches one case
and its documents, calls no model and writes nothing to the bucket. Read the lines:

- `dry run: N cases queued; a morning would code X (money allows Y tonight; Z held back).` With a
  fresh $10 key, `Y` is 30: the cap is $9, and $9 divided by $0.30 is 30. A `Y` that is much
  lower means the key has already spent, or its limit is lower than $10.
- It stops with a line from section 6 (`key-unreachable` and others) if a check fails.

**Check the reset period.** The dry run does not print the key's reset period; decision 0170
assumes it is monthly. You confirm it: open OpenRouter, your account's API keys page, the live
key, and read the limit and its reset setting. It must read $10 and monthly. This is for you to
confirm; nothing in the code does.

**Step 2: ask Claude to ask you.** Claude asks before the first cloud night, saying what it
costs (about 30 cases, about $0.15, about 45 minutes) and how long it runs.

**Step 3: enable the schedule. This is the go-ahead.** From the `infra` folder, the full context,
with the real digest:

```
cdk deploy NtsbLiveStack --profile ntsb -c recorder_bucket=<recorder bucket> -c alert_email=<alert email> -c github_oidc_provider_arn=<provider arn> -c live_image_digest=<digest> -c ledger_branches=main,s4-predictions-and-resolution -c live_schedule=enabled
```

The next 06:00 UTC night is the first one. The backfill (the cases closed since 23 September 2026
and not yet coded) takes about three nights because a night is limited by money and time.

**Step 4: after the first night.**

1. Read the night's email and the log (the command in section 2).
2. `make s4-export`. Then run the ledger job by a push to the S4 branch and wait for it to finish
   (section 9, "Run the job before the merge"; the 10:00 UTC schedule does not run before the
   merge). Then `make s4-verify-ledger`, then `make s4-report`. `docs/results/s4-live.txt` is
   counts only: commit it yourself or ask Claude.
3. **The alarm state test.** The alarm sits in `ALARM` from the deploy until the first finished
   night, which sends an `OK` email. Run the test only once the alarm shows `OK`, because an alarm
   already in `ALARM` sends nothing. Find its name, then check its state. **Verify on first use:** the name starts with the stack
   name and the alarm's id `MissedNight`; if the command prints nothing, list all alarms
   (`aws cloudwatch describe-alarms --region eu-west-2 --profile ntsb --query "MetricAlarms[].AlarmName"`).
   ```
   aws cloudwatch describe-alarms --alarm-name-prefix NtsbLiveStack-MissedNight --region eu-west-2 --profile ntsb --query "MetricAlarms[].[AlarmName,StateValue]" --output text
   ```
   When it reads `OK`:
   ```
   aws cloudwatch set-alarm-state --alarm-name <name> --state-value ALARM --state-reason "S4 test" --region eu-west-2 --profile ntsb
   ```
   An `ALARM` email should arrive within a minute or two. CloudWatch sets the alarm back to its
   real state (`OK`) at its next check and sends an `OK` email. **Verify on first use:** the next
   check can take up to one 6-hour period (the alarm's period), so the `OK` email may come hours
   later. Write the date of the `ALARM` email as `alarm_test_fired` in the attestation file.
4. **Record what you saw.** Two of the closing conditions are your word; the report cannot see
   them. Write the dates in a small file the report reads:
   ```
   cat > /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/live-attest.json <<'JSON'
   {"alert_email_received": "YYYY-MM-DD", "alarm_test_fired": "YYYY-MM-DD", "mac_key_removed": ""}
   JSON
   ```
   Replace each `YYYY-MM-DD` with a real date written that way (`2026-10-14`). The report reads
   each value as a date: a value that is not a date counts as "not met". Fill `mac_key_removed`
   after section 11. The report prints the dates, and only the dates, in
   `docs/results/s4-live.txt`. The attestation file is not committed.

## 11. Remove the Mac's key, then move to `main`

**Remove the Mac's key after the first good cloud night** (decision 0171). The old IAM user
`ntsb-live-reader` and its access key let the Mac read the recorder's store for S3.3. Each
command uses `--profile ntsb` (sign in first with `aws login`):

1. List the keys: `aws iam list-access-keys --user-name ntsb-live-reader --profile ntsb`. It may
   return two keys. Note each `AccessKeyId`.
2. `aws iam delete-access-key --user-name ntsb-live-reader --access-key-id <id> --profile ntsb`,
   once for each key. A user with a key left cannot be deleted in step 4.
3. `aws iam delete-user-policy --user-name ntsb-live-reader --policy-name live-shadow-read-store --profile ntsb`
4. `aws iam delete-user --user-name ntsb-live-reader --profile ntsb`
5. `pass rm aws/ntsb-live-reader`
6. Remove the `[profile ntsb-live]` block from `~/.aws/config`. The `ntsb` profile stays.
7. Put today's date in `mac_key_removed` in `live-attest.json` (section 10, step 4).

**After the stage pull request is merged** (a merge commit, decision 0033), the task moves from an
image built on the S4 branch to an image built from `main`, and the branch's trust in the ledger
role is removed. From a clean `main` checkout (the `cdk` command from its `infra` folder):

1. From the project folder, `make s4-image CONFIRM=yes` prints the new digest (do this only when
   no live run is unfinished, section 5).
2. Deploy once, with `main` as the only ledger branch and the schedule still on:
   ```
   cdk deploy NtsbLiveStack --profile ntsb -c recorder_bucket=<recorder bucket> -c alert_email=<alert email> -c github_oidc_provider_arn=<provider arn> -c live_image_digest=<new digest> -c ledger_branches=main -c live_schedule=enabled
   ```
3. The close-out commit removes the S4 branch from the ledger workflow's `push` trigger. From
   now on the 10:00 UTC schedule runs the job, because the file is on `main`. Check that the
   next 10:00 UTC run still signs in.

---

## Glossary

- **Alarm.** A CloudWatch rule that sends an email when the metric says no night finished for 30
  hours.
- **Backfill.** The cases closed since 23 September 2026 and before the live queue began. The
  first nights code them; the list is fixed once, with a SHA-256.
- **Bucket.** A named place in S3 that holds files. The live bucket is private.
- **Digest.** A long code (`sha256:` and 64 characters) that names exactly one image. The task
  runs the image by its digest, so it cannot change under you.
- **ECR.** AWS's store for container images. The repository is `ntsb-live`.
- **Export.** The board's data: JSON files in the format `board/1`, built from the bucket.
- **Fargate task.** A small computer AWS starts for one job and stops when it ends. You pay by the
  second it runs.
- **Image.** The packaged program the task runs.
- **Ledger.** A public list, `ledger.jsonl` on the `ledger` branch, with the SHA-256 of every run
  and night manifest. It shows results were not changed later.
- **Later score.** A grade given after the case was coded, when the NTSB's codes arrive.
- **Manifest.** A list of a folder's files with their sizes and SHA-256 hashes.
- **Marker.** The empty file `nights/<date>/started`. It stops a second task on the same day.
- **Metric.** One number the task sends to CloudWatch after a finished night.
- **OIDC provider.** The way GitHub proves to AWS who is signing in, with no stored password.
- **Parameter Store.** An AWS place for secret values. The task reads the live OpenRouter key from
  it.
- **Resume.** Finishing an unfinished run from the replies already saved.
- **Revision.** One version of the task's definition. Each deploy makes a new one.
- **Run folder.** A folder under `runs/` in the bucket that holds one run's records.
- **Schedule.** The rule that starts the task at 06:00 UTC. It is off until you enable it.
- **SHA-256.** A fingerprint of a file. A changed file has a different one.
- **SNS.** AWS's message service. It sends the alert emails.
- **Unfinished run.** A live run folder with no `run.jsonl`, or whose `run.jsonl` has no
  `finished` time.
- **UTC.** The world time standard. UK summer time is UTC plus 1 hour.
