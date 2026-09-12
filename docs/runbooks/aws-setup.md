# Runbook — AWS account setup

*First run: 2026-09-12, completed the same day. Region `eu-west-2` (London). Decision
behind this: `docs/decisions/0010-separate-aws-account.md`.*

**What this sets up.** An AWS Organization with the existing account (which hosts
`floyda.dev`) as the management account, plus a separate member account that holds
everything this project creates. Nothing this project does can reach the profile site,
because the credentials do not extend there.

**Read the warning in stage 3 before running stage 3.** It is the one step that cannot be
undone quickly.

## As built

Completed 2026-09-12. The organization, both accounts, the command-line profile and the
budget are in place, and every check in the verification table below passes.

**Account numbers, email addresses and profile contents are in
`docs/runbooks/aws-accounts.local.md`, which is not in version control.** They are not
secrets, but they are account-specific and this repository is public. The procedure and
the reasoning are here; the values are there.

Shape of what exists:

| | |
|---|---|
| Organization | feature set `ALL`, management account holds `floyda.dev` |
| Project account | separate member account, holds everything this project builds |
| Command-line identity | IAM user with `AdministratorAccess` and no active access key; `aws login` supplies short-lived credentials |
| Project profile | `ntsb` — assumes `OrganizationAccountAccessRole`, region `eu-west-2` |
| Budget | $30/month, filtered to the project account, alerting at 50% actual and 100% forecast |

---

## Stage 0 — Root, used once and briefly

**You cannot avoid the root user entirely, but its job here is small.** Root is the
account's original identity: unlimited power, cannot be restricted. Use it for the three
setup tasks below, then leave it alone — afterwards it is needed only for closing the
account, changing the root email or billing details, changing the support plan, or
recovering lost access.

In the browser, signed in as root:

1. **Enable MFA on the root user.** Root protected only by a password is the largest
   single risk on the account.
2. **Check for root access keys and delete any that exist.** IAM -> Security credentials.
   A root access key is a permanent, unrestricted credential with no good use case.
3. **Confirm the IAM user has `AdministratorAccess`** (or at least `organizations:*`).
   Creating the organization in stage 2 needs it. Doing this now avoids a second root
   session later.

Then sign out of root.

**On the existing IAM user** (which is the identity used from here on). An IAM user has
two independent kinds of access — a password for the browser, and access keys for
programmatic use. A user created for programmatic use only has no password, and therefore
cannot sign in to the console at all. `aws login` works from a console session, so the
password is the one that matters here:

4. **Enable console access.** IAM -> Users -> the user -> Security credentials -> Console
   sign-in -> Enable, and set a password. Without this the user cannot sign in and stage 1
   cannot run.
5. **Enable MFA** on it, same tab.
6. **Delete any access keys it has** that nothing depends on. Stage 1 gets command-line
   access without one.
7. **Find the IAM sign-in URL.** IAM -> Dashboard -> "Sign-in URL for IAM users in this
   account", of the form `https://<account-id>.signin.aws.amazon.com/console`. The normal
   console sign-in page defaults to the root user; this URL goes straight to the IAM user
   form, and the standard page offers it behind an "IAM user" toggle. An account alias can
   be set on the same page to make the URL friendlier.

**Never run `aws login` as root.** Whatever identity that session holds becomes the
credentials every later command runs under, including Claude's. As the IAM user, access
can be narrowed or revoked by disabling that one user; as root it cannot be restricted at
all.

**IAM Identity Center is deliberately not used.** Plain IAM plus `aws login` already gives
short-lived command-line credentials with no stored secret, and the member account is
reached by assuming a role. Identity Center would add a portal, an identity store and
permission sets to manage, which buys nothing for one person and two accounts. It starts
to earn its place at three or more accounts, or a second person, or a need to revoke
access centrally. Revisit then.

---

## Stage 1 — Command-line access with no stored secret

Sign out of root first, then sign in as the IAM user using the sign-in URL from stage 0.

```
aws login
```

This must be run in a real terminal — it opens a browser and will fail if standard input
is not a terminal. Sign in as the IAM user. The CLI stores short-lived credentials and a
refresh token, and renews them while the refresh token is valid. No access key is created.

```
aws sts get-caller-identity
```

The ARN must end in `:user/<name>`, not `:root`. Note the account number — the
*management account*.

Confirm the user really holds administrator permissions, rather than assuming it from a
console tab:

```
aws iam list-attached-user-policies --user-name <name>
aws iam list-groups-for-user --user-name <name>
```

`AdministratorAccess` should appear directly or on one of the groups. If it does not,
stage 2 fails with an access-denied error naming the missing permission, and root can
attach the policy.

**Why this rather than an access key.** An access key is a long-lived secret in a file. If
it leaks, someone else holds the account until it is noticed and revoked. These
credentials expire on their own.

---

## Stage 2 — Create the Organization

The IAM user can do this if it holds administrator permissions; root is not required.

```
aws organizations create-organization --feature-set ALL
```

Nothing about `floyda.dev` changes: no resources move, no DNS changes, no downtime. It
makes the existing account the management account of a new organization. `ALL` features
(rather than consolidated billing alone) is what makes the account isolation possible.

```
aws organizations describe-organization
```

**Reversibility.** An organization containing only the management account can be deleted
again. Once a member account exists, it has to be removed first.

---

## Stage 3 — Create the member account and reach it

**Read this before running it.** A new AWS account needs a root email that has never been
used for an AWS account, and **closing an account takes about 90 days, during which the
address cannot be reused**. This choice is effectively permanent.

Gmail treats anything after a `+` as the same inbox, so this is a distinct address to AWS
that still reaches the same place:

```
aws organizations create-account \
  --email "<PROJECT_ROOT_EMAIL>" \
  --account-name "ntsb-probable-cause"
```

It returns a request identifier and completes in the background:

```
aws organizations list-create-account-status --states SUCCEEDED
```

Note the new account number — the *project account*.

`create-account` also leaves a role called `OrganizationAccountAccessRole` in the new
account, assumable from the management account. That is how it is reached without a second
login. In `~/.aws/config`:

```
[profile ntsb]
role_arn = arn:aws:iam::<PROJECT_ACCOUNT_ID>:role/OrganizationAccountAccessRole
source_profile = default
region = eu-west-2
output = json
```

```
aws sts get-caller-identity --profile ntsb
```

The account number printed must be the **project** account. If it prints the management
account, stop — the profile is not being applied, and the next command would land on the
account holding the live site.

**Verified 2026-09-12:** `source_profile = default` chains cleanly off an `aws login`
session. `aws login` writes `login_session = <user arn>` into the default profile and
caches credentials under `~/.aws/login/cache/`; the assume-role provider resolves the
default profile through that chain without an access key anywhere.
`credential_source = Environment` is not needed and would not work here, as no AWS
environment variables are set.

---

## Stage 4 — Budget alarm

$30 a month, alerting before the ceiling is reached rather than after.

**The budget lives in the management account, filtered to the project account** — not in
the project account itself. Under consolidated billing, a member account's cost data flows
up to the management account, and a member account cannot see its own billing unless that
is explicitly enabled. Creating it in the management account with a `LinkedAccount` filter
uses data that is certain to exist and needs nothing extra turned on.

Two thresholds: a warning at 50% of actual spend, and a forecast alert when the month is
projected to exceed the ceiling. The forecast alert is the useful one — it fires while
there is still time to act. Both notify `<ALERT_EMAIL>`.

The Budgets API is global and answers on `us-east-1`, so the command carries
`--region us-east-1` regardless of where resources live.

```
aws budgets create-budget \
  --account-id <MANAGEMENT_ACCOUNT_ID> \
  --budget file://budget.json \
  --notifications-with-subscribers file://notifications.json \
  --region us-east-1
```

`budget.json` sets `BudgetLimit` to `{"Amount": "30", "Unit": "USD"}`, `TimeUnit` to
`MONTHLY`, `BudgetType` to `COST`, and `CostFilters` to
`{"LinkedAccount": ["<PROJECT_ACCOUNT_ID>"]}`.

Verify with `describe-budget` and `describe-notifications-for-budget`.

**Note on cost.** The first two budgets per account are free; beyond that they are charged
per day. Two is enough.

**Note on what a budget is and is not.** It notifies. It does not stop spending. The
per-case cost cap enforced in the agent's code is the control that actually refuses; the
budget is the backstop that catches a pattern the cap did not anticipate. A service
control policy would be a third, harder layer — see the note in stage 6.

---

## Stage 5 — Prepare the region for deployments

CDK needs a one-time setup in each account and region it deploys to. It creates a small
bucket and a few roles it uses to ship stacks.

```
cdk bootstrap aws://<PROJECT_ACCOUNT_ID>/eu-west-2 --profile ntsb
```

Run this once, when there is a first stack to deploy (build stage S5). Listed here so the
sequence is complete.

---

## Stage 6 — Deferred items

Neither is needed before there is something to deploy. Both are listed so they are not
rediscovered later.

**DNS delegation.** `floyda.dev`'s hosted zone stays in the management account. When the
site is ready to publish, a hosted zone for `ntsb.floyda.dev` is created in the project
account, and a single NS record is added to the parent zone pointing at it. After that the
project's own stack manages its records and never touches the parent zone.

**Service control policy.** The organization has `SERVICE_CONTROL_POLICY` enabled
(confirmed 2026-09-12). A service control policy sets the outer limit of what an account
is permitted to do at all, regardless of what any IAM policy inside that account grants.
Applied to the project account it could, for example, deny every region except
`eu-west-2`, or deny services this project has no business using.

Why it is worth doing rather than just interesting: it is the only one of the three cost
and blast-radius controls that *refuses* rather than reports. The per-case cap in the
agent's code stops a runaway case; the budget notifies when a pattern emerges; a service
control policy makes a whole class of spending impossible. Cheap to add, and a concrete
thing to point at when asked how the cost ceiling is actually enforced.

Not applied yet — it should be written once the stack's real service list is known, so it
constrains without blocking legitimate work.

---

## Who uses what

| identity | used for | used by |
|---|---|---|
| Root | Stage 0 only, then: closing the account, changing root email or billing, changing support plan, recovering lost access | Andy, in a browser, rarely |
| IAM user (management account) | Creating the organization and member accounts | Andy, and Claude via the default profile |
| `OrganizationAccountAccessRole` (project account) | Everything this project builds and deploys | Andy, and Claude via the `ntsb` profile |

Claude never uses root. Access is through short-lived credentials from `aws login`, which
can be revoked by disabling the IAM user without touching anything else.

---

## Checks that must pass before anything is deployed

Run these after any change to the account structure. Results below are from 2026-09-12.

| check | command | expected | result |
|---|---|---|---|
| Organization exists | `aws organizations describe-organization` | management account is yours, features `ALL` | `<ORG_ID>`, `ALL` |
| Project account exists | `aws organizations list-accounts` | two accounts, both `ACTIVE` | pass |
| Profile targets the project account | `aws sts get-caller-identity --profile ntsb` | `<PROJECT_ACCOUNT_ID>` | pass |
| Profile region | `aws configure get region --profile ntsb` | `eu-west-2` | pass |
| Budget in place | `aws budgets describe-budget --account-id <MANAGEMENT_ACCOUNT_ID> --budget-name ntsb-probable-cause-monthly --region us-east-1` | $30, filtered to the project account | pass |
| Profile site untouched | `curl -sI https://floyda.dev` | HTTP 200 | pass |
| No root access keys | `aws iam get-account-summary --query SummaryMap.AccountAccessKeysPresent` | `0` | pass |
| Root MFA enabled | `aws iam get-account-summary --query SummaryMap.AccountMFAEnabled` | `1` | pass |
| No live access keys on the IAM user | `aws iam list-access-keys --user-name <IAM_USER>` | empty, or all `Inactive` | two keys present, both `Inactive` |

**Open item from the last run.** The the IAM user still has two access keys
(`<ACCESS_KEY_ID>`, `<ACCESS_KEY_ID>`), both deactivated. Deactivated is not the
same as deleted: a deactivated key can be switched back on, so the secret still matters. If
nothing depends on them they should be deleted. Check first — an existing deployment for
`floyda.dev`, a CI job, or a local tool may still be configured to use one, in which case
deleting it breaks that rather than this project.

---

## Glossary

**Access key.** A long-lived username-and-password pair for programmatic access. Avoided
here in favour of short-lived credentials.

**Account (AWS).** A container for resources, not a login. Resources in one account are
invisible to another unless explicitly shared. AWS's real isolation boundary.

**Bootstrap (CDK).** One-time preparation of an account and region so deployments can run.

**Consolidated billing.** One bill for every account in an organization, itemised per
account.

**Hosted zone.** The Route 53 object holding the DNS records for a domain.

**Management account.** The account at the top of an organization. Pays the bills and can
create member accounts.

**Member account.** An account created inside an organization.

**Organization.** A group of AWS accounts managed and billed together.

**Profile.** A named set of credentials and settings in `~/.aws/config`, selected with
`--profile`.

**Root email.** The address an AWS account is registered to. Cannot be reused for about 90
days after an account is closed.

**Root user.** The original identity of an AWS account, holding unlimited power and unable
to be restricted. Used to create the identities that replace it, then left alone.

**IAM.** AWS's identity service: users, groups, roles and policies. Global — it has no
region.

**IAM Identity Center.** A separate, regional sign-in service for an organization. Not
used here; see stage 0 for why.

**MFA.** Multi-factor authentication: a second proof of identity beyond a password.
