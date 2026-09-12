# 0010 — The project runs in its own AWS account under Organizations

## Context

Andy's AWS account already hosts `floyda.dev`, his profile site: S3 behind CloudFront,
with Route 53 holding the domain (confirmed 2026-09-12 from public DNS and response
headers). That site is live and must not be put at risk by a project being built by an
agent that is learning the account as it goes.

## Decision

Create an AWS Organization with the existing account as the management account, and a
separate member account for this project. All project resources live there. `floyda.dev`
stays where it is.

DNS spans the boundary: the `ntsb.floyda.dev` subdomain is delegated to a hosted zone in
the project account by a single NS record added once in the parent zone. After that, the
project's CDK manages its own records with no access to the parent zone.

## Why

1. **A hard boundary, not a careful one.** An account is AWS's real isolation unit. With
   separate accounts, no mistake in this project's code or in an agent's command can touch
   the profile site, because the credentials do not reach it. Same-account separation
   relies on getting every policy and every command right, every time.
2. **Cost becomes readable.** Consolidated billing reports per account, so this project's
   spend is a number to look at rather than something to untangle from the profile site's.
   The project claims a cost ceiling; being able to show it per account supports that.
3. **It is what the situation actually warrants.** The alternative is defensible for a
   throwaway, but there is a live site in the account and an agent with credentials.

## What it costs

- Organizations itself is free; resources are billed as before, on one consolidated bill.
- A one-time setup: create the organization, create the member account, configure access,
  add one NS record to delegate the subdomain.
- An ongoing discipline: knowing which account a command is pointed at. Mitigated by
  named profiles and by the `make` interface, which pins the profile.

## What this rules out

- **Same account, separate stack.** Simplest to operate, and `cdk diff` would show changes
  before they happened. Rejected because it is a discipline boundary rather than a real
  one, and the thing on the other side of it is a live site.
- **A second unrelated AWS account outside an organization.** Same isolation, but separate
  bills, no consolidated cost view, and no central place to manage access.

## Status

Accepted, 2026-09-12.
