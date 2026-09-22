# 0069 — The NTSB key reaches the scheduled task from AWS Parameter Store, encrypted

## Context

The recorder runs unattended as a scheduled Fargate task (0004) and needs one secret, the
NTSB API key. No model is called in this stage, so no OpenRouter key is needed. Today the key
lives in `pass` on Andy's Mac and is read into an environment variable by a shell script;
nothing in the project said how a cloud task gets it. The standing rule is that a key never
reaches session data, git, or a printed line.

## Decision

The key is stored once in AWS Systems Manager Parameter Store as an encrypted
(`SecureString`) parameter, written from `pass` by Andy so it never appears on screen:
`aws ssm put-parameter --name /ntsb/api-key --type SecureString --value "$(pass show api/ntsb)" --profile ntsb`.
The task definition references the parameter; AWS reads it at task start and injects it as
the `NTSB_API_KEY` environment variable. The same step adds the OpenRouter key when S4 needs
it.

## Why

1. **The key is never in the image, the CDK code, the console's task definition or git.**
2. **Free at this size**, and one command in the runbook.
3. **The program is unchanged**: it reads `NTSB_API_KEY` from the environment as it does today.

## What this rules out

- **AWS Secrets Manager.** The same property with automatic rotation, which the NTSB key does
  not support, at about $0.40 a month per secret.
- **A plain environment variable in the task definition.** The key would be readable in the
  console and in CDK output. Not acceptable.

## Status

Accepted, 2026-09-22.
