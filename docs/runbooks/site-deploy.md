# Runbook — deploying the public site's stacks

*Read this before you start.* It takes the three stacks in `infra/site_stacks.py` (S5 step 1,
spec §18) from nothing to `https://ellery.demo.floyda.dev` showing the holding line, rebuilt by
**CodeBuild**. Until you decide to launch (spec §20), the only thing the build can publish is
the holding line: `site/scripts/publish.sh` refuses every other mode.

Every term in **bold** the first time it appears is in the glossary at the end. Commands use
`--profile ntsb`, the project's own AWS account (`docs/runbooks/aws-setup.md`), except Stage 3,
which is in your **personal account**, the one holding `floyda.dev`. Run them from the S5
worktree, `/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/.claude/worktrees/s5-public-site`;
after S5 merges, from the main checkout.

---

## What you will have at the end

- `https://ellery.demo.floyda.dev` shows "Ellery" and "Coming soon.", over HTTPS, with security
  headers, and a missing page shows a 404 page.
- A push to the site's branch starts a build that publishes the holding line again.
- Once S4's live stack is deployed and its bucket's name is given (Stage 6), each night's export
  starts a build too.
- A failed build emails you.
- The bill: **$0 a month expected**, on CloudFront's **flat-rate Free plan**, which also covers
  the zone (spec §18.3, checked 2026-10-12).

## Before you start

- `docs/runbooks/aws-setup.md`'s checks pass, and `docs/runbooks/recorder-deploy.md`'s Stage 1
  tools (`aws`, `cdk`, `uv`) are installed.
- `make check` is green on the branch you deploy from.

---

## Stage 1 — Bootstrap `us-east-1` (once)

The recorder bootstrapped CDK in `eu-west-2` only. The zone, the certificate and the **web ACL**
live in `us-east-1`, so CDK needs its bootstrap there too:

Every command from here on runs in the **S5 worktree's** `infra` folder, not the main checkout,
whose `main` branch has no site stacks until S5 merges ("No stacks match the name(s)" means the
wrong folder). CDK's banner about an untested Node version is harmless; the `export` hides it.

```bash
cd /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/.claude/worktrees/s5-public-site/infra
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1
uv run cdk bootstrap aws://$(aws sts get-caller-identity --profile ntsb --query Account --output text)/us-east-1 --profile ntsb
```

The account number is read from your credentials and never written to a file.

## Stage 2 — The zone

```bash
uv run cdk deploy NtsbSiteDnsStack --profile ntsb
```

Copy the four name servers from the `NameServers` output. The zone is free while it is on the
flat-rate plan (Stage 6); until then it is $0.50 a month.

## Stage 3 — Delegate `demo.floyda.dev` (your personal account)

In the Route 53 console of your **personal account**, open the `floyda.dev` hosted zone and
create one record:

- Record name: `demo`
- Type: `NS`
- Value: the four name servers from Stage 2, one per line
- TTL: `172800`

Check from your Mac until all four appear (minutes, usually):

```bash
dig NS demo.floyda.dev +short
```

## Stage 4 — The certificate and the web ACL

```bash
uv run cdk deploy NtsbSiteEdgeStack --profile ntsb
```

It waits until the certificate's DNS check succeeds, usually a few minutes. If it waits more
than 30 minutes, Stage 3's records are not visible yet: check `dig` again.

## Stage 5 — Connect CodeBuild to GitHub (once)

CodeBuild needs to read the repository and receive a message on each push. **Make the connection
in the project account.** Signing in to the console puts you in your personal account; switch
role to the project account first (`docs/runbooks/recorder-deploy.md`, "Console access"). On
2026-10-13 the first connection was made in the personal account by mistake, and the site
stack's webhook failed with "Access token not found".

1. With the console in the **project account**, region **Europe (London)**: **Developer Tools →
   Settings → Connections → Create connection.** Provider: GitHub. Name: `ntsb-site`. GitHub
   offers the **AWS Connector for GitHub** app; if it is already installed, choose the existing
   installation. Its repository access must be **Only select repositories**:
   `floyda/ntsb-probable-cause`. Finish; the status must read **Available**.
2. Copy the connection's ARN:

   ```bash
   aws codeconnections list-connections --region eu-west-2 --profile ntsb \
     --query 'Connections[].[ConnectionName,ConnectionStatus,ConnectionArn]' --output text
   ```

   It lists every connection in the project account, whatever its name; use the GitHub one
   whose status is `AVAILABLE`. The site stack names this connection on the build project (`github_connection_arn`), so no
   account-wide CodeBuild setting is needed.

Read the app's install screen before accepting: the AWS Connector for GitHub asks for access to
the repository's code, commit statuses and webhooks, including write access. CodeBuild uses it to
read the repository and to create one webhook, so pushes start a build. The build itself writes
nothing back: the stack turns off commit-status reporting (`report_build_status=False`). Limit
the installation to this one repository.

## Stage 6 — The site stack

```bash
uv run cdk deploy NtsbSiteStack \
  -c alert_email=<your address> \
  -c site_source_branch=s5-public-site \
  -c github_connection_arn=<the ARN from Stage 5> \
  --profile ntsb
```

- **Pass the same `-c` values on every deploy of `NtsbSiteStack`.** A deploy without
  `alert_email` removes the email subscription; one without `live_bucket_name` removes the rule
  on S4's export; one without `github_connection_arn` removes the push webhook. The zone and certificate stacks do not depend on them.
- After S5 merges, use `-c site_source_branch=main`.
- After S4's live stack is deployed, add `-c live_bucket_name=<S4's LiveBucketName output>`.
  Without it the stack has no rule on S4's bucket and no access to it.
- AWS emails a subscription request to the address: **confirm it**, or build failures reach no
  one.
- Go straight on to Stage 7: until the first build, the bucket is empty and every address,
  even a missing page, answers 403.

**Check the plan is active.** CloudFront console → the distribution → **Pricing plan**: it must
read **Free**, **Active**. If it does not, the web ACL bills pay-as-you-go (about $5 a month
plus $1 a rule); delete `NtsbSiteStack` and ask in the session before trying again.

## Stage 7 — The first build

```bash
aws codebuild start-build --project-name <BuildProjectName output> --profile ntsb --region eu-west-2
```

Watch it in the CodeBuild console; it takes about a minute. Then open
`https://ellery.demo.floyda.dev` on your phone. Check from the Mac:

```bash
curl -sSI https://ellery.demo.floyda.dev/ | head -20
curl -sS -o /dev/null -w '%{http_code}\n' https://ellery.demo.floyda.dev/nothing-here
```

The first shows `HTTP/2 200` with `strict-transport-security` and `content-security-policy`
lines; the second prints `404`.

## What it costs

From spec §18.3 (AWS pricing pages, read 2026-10-11, and the flat-rate plan's guide, read
2026-10-12):

| part | cost |
|---|---|
| CloudFront, web ACL and zone, on the Free plan | $0; never an overage charge |
| site bucket | $0, inside the plan's 5 GB S3 credit |
| CodeBuild | about $0: 100 free minutes a month, about 1 to 3 a build |
| certificate, event rules, alert email | $0 |

Past the plan's allowance (1 million requests and 100 GB a month) AWS emails at 50%, 80% and
100%. Sustained use well past it may see delivery slowed until the plan is upgraded (Pro, $15 a
month).

## Taking it down (if you ever need to)

Newest first. The bucket is kept on delete (`RETAIN`); empty and delete it by hand if wanted.

1. `uv run cdk destroy NtsbSiteStack -c alert_email=<address> --profile ntsb` (this cancels the
   Free plan at once).
2. `uv run cdk destroy NtsbSiteEdgeStack --profile ntsb`
3. In your personal account, delete the `demo` NS record in `floyda.dev`.
4. `uv run cdk destroy NtsbSiteDnsStack --profile ntsb`
5. Remove the `ntsb-site` connection and the GitHub app installation if nothing else uses them.

---

## Glossary

- **CodeBuild**: AWS's build service. Here it fetches the repository, runs
  `site/scripts/publish.sh`, and copies the result to the site's bucket.
- **Flat-rate Free plan**: a CloudFront pricing plan at $0 a month with a usage allowance and no
  overage charges. It needs a web ACL on the distribution.
- **Holding line**: the one-line page the address shows until you decide to launch.
- **Name server (NS) record**: the record in `floyda.dev` that hands the `demo` subdomain to
  the zone in the project account.
- **Personal account**: your AWS account that holds `floyda.dev`, separate from the project
  account.
- **Web ACL**: an AWS WAF rule set attached to the distribution. Here it allows everything except
  an address making more than 600 requests in 5 minutes.
