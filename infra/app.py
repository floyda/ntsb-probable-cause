"""CDK entry point for the recorder's AWS stack (S2.5 Task 13).

Run with `cd infra && cdk synth` (no credentials needed) or `cd infra && cdk deploy --profile
ntsb` (`docs/runbooks/recorder-deploy.md` walks the whole sequence).

`env` fixes the region (`eu-west-2`, decision 0010) and leaves the account **unset** --
deliberately, and not the same thing as reading `CDK_DEFAULT_ACCOUNT` from the environment
(this file's first version did that; see the dated Deviation entry that corrects it). Leaving
the account unset keeps the stack "account-agnostic": `cdk deploy --profile ntsb` still
targets the right account, because the CDK CLI resolves an unset account from the active
profile's credentials at deploy time -- the same mechanism every other command in the runbook
relies on via `--profile ntsb`, not a new one.

The reason this matters for `cdk synth`: `ec2.Vpc`'s explicit `availability_zones` list (in
`recorder_stack.py`) does not, by itself, avoid a real AWS lookup -- CDK's `Vpc` construct
still reads `Stack.availabilityZones` to validate the given list is a real subset, and that
property only returns the CloudFormation pseudo-parameter list (`Fn::GetAZs`, no lookup)
when the stack's account is *unresolved*. The moment account becomes a concrete value (as
reading `CDK_DEFAULT_ACCOUNT` would make it, whenever that variable happens to be set in the
shell), the same property attempts a real, credentialed lookup instead -- which is exactly
what happened here: `cdk synth` failed outright with `CDK_DEFAULT_ACCOUNT` set and no real
credentials behind it, and would otherwise have written the account number into
`infra/cdk.context.json` (also now gitignored, as defence in depth). Leaving the account
unset sidesteps this entirely, for every invocation of `cdk synth`, regardless of what is set
in the calling shell.

`github_oidc_provider_arn` is CDK context, not an environment variable: pass
`-c github_oidc_provider_arn=<arn>` to import an account's existing
`token.actions.githubusercontent.com` provider instead of creating a new one (an account may
hold only one provider per URL). The runbook shows Andy how to check first.
"""

import aws_cdk as cdk

from recorder_stack import NtsbRecorderStack

app = cdk.App()

NtsbRecorderStack(
    app,
    "NtsbRecorderStack",
    env=cdk.Environment(region="eu-west-2"),
    github_oidc_provider_arn=app.node.try_get_context("github_oidc_provider_arn"),
)

app.synth()
