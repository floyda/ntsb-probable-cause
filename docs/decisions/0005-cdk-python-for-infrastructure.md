# 0005 — AWS CDK in Python for infrastructure

## Context

The stack is small: a scheduled task, a container registry, a bucket, a distribution, a
schedule and a budget alarm. It still has to be defined as code so it is reproducible and
reviewable rather than clicked into existence.

## Decision

AWS CDK, Python, under `infra/`.

## Why

1. Keeps the repository in one language, so infrastructure and application share tooling,
   formatting and type checking rather than introducing a second toolchain for six
   resources.
2. The stack is small enough that CDK's main cost — CloudFormation underneath, with its
   own failure modes — stays manageable.

## What this rules out

- **Terraform.** More widely legible to a reviewer, explicit state, and no CloudFormation
  drift surprises. Rejected for language consistency at this size; it would be the better
  choice if the stack grew or if several people maintained it.
- **AWS SAM.** Lambda-centric, so it does not fit the decision in 0004.

## Status

Accepted. See `docs/specs/2026-09-12-architecture-and-roadmap.md` §6.
