"""CDK entry point for the recorder's AWS stack (S2.5 Task 13).

Run with `cd infra && cdk synth` (no credentials needed) or `cd infra && cdk deploy --profile
ntsb` (`docs/runbooks/recorder-deploy.md` walks the whole sequence).

`env` reads the account from `CDK_DEFAULT_ACCOUNT`, which is unset in a plain `cdk synth` --
that is deliberate (controller note 2): synth must work offline, with no AWS credentials and
no network call, so nothing here ever looks up an existing account or VPC. `cdk deploy
--profile ntsb` sets `CDK_DEFAULT_ACCOUNT` itself, from the profile's credentials, before this
file runs.

`github_oidc_provider_arn` is CDK context, not an environment variable: pass
`-c github_oidc_provider_arn=<arn>` to import an account's existing
`token.actions.githubusercontent.com` provider instead of creating a new one (an account may
hold only one provider per URL). The runbook shows Andy how to check first.
"""

import os

import aws_cdk as cdk

from recorder_stack import NtsbRecorderStack

app = cdk.App()

NtsbRecorderStack(
    app,
    "NtsbRecorderStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region="eu-west-2",
    ),
    github_oidc_provider_arn=app.node.try_get_context("github_oidc_provider_arn"),
)

app.synth()
