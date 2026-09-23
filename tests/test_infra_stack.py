"""``infra/recorder_stack.py``, the recorder's AWS stack (S2.5 Task 13, spec S9.2).

``aws-cdk-lib`` is built on `jsii`, which shells out to a Node.js child process at import and
synth time. CI's test job (``ubuntu-latest``) has Node preinstalled, and so does this Mac, but
a stricter environment might not -- so this whole module is skipped, with a stated reason,
rather than failing an unrelated way, when ``node`` is not on ``PATH``.

Building the template goes through the real jsii kernel (a Node subprocess per app), which is
slow enough (low seconds) that it is built once per module, not once per test -- see the
module-scoped ``template`` fixture.
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

if shutil.which("node") is None:
    pytest.skip(
        "aws-cdk-lib needs Node.js (via jsii) at import time; none found on PATH",
        allow_module_level=True,
    )

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

_INFRA_DIR = Path(__file__).resolve().parents[1] / "infra"
sys.path.insert(0, str(_INFRA_DIR))
from recorder_stack import NtsbRecorderStack  # noqa: E402 -- must follow the sys.path insert above

_TEST_ACCOUNT = "123456789012"
_TEST_REGION = "eu-west-2"


def _build_template(*, github_oidc_provider_arn: str | None = None) -> Template:
    app = cdk.App()
    stack = NtsbRecorderStack(
        app,
        "TestNtsbRecorderStack",
        env=cdk.Environment(account=_TEST_ACCOUNT, region=_TEST_REGION),
        github_oidc_provider_arn=github_oidc_provider_arn,
    )
    return Template.from_stack(stack)


@pytest.fixture(scope="module")
def template() -> Template:
    """The stack's CloudFormation template, creating its own OIDC provider (the default path)."""
    return _build_template()


def _all_policy_statements(tpl: Template) -> list[dict[str, Any]]:
    """Every statement in every ``AWS::IAM::Policy`` and ``AWS::IAM::Role`` inline document.

    Flattened across resources so the "no bare wildcard" checks (Test group 5) can scan the
    whole stack in one pass rather than one resource type at a time.
    """
    statements: list[dict[str, Any]] = []
    as_json = tpl.to_json()
    for resource in as_json["Resources"].values():
        props = resource.get("Properties", {})
        documents = []
        if "PolicyDocument" in props:
            documents.append(props["PolicyDocument"])
        if "AssumeRolePolicyDocument" in props:
            documents.append(props["AssumeRolePolicyDocument"])
        for policy in props.get("Policies", []):
            documents.append(policy["PolicyDocument"])
        for document in documents:
            stmts = document["Statement"]
            statements.extend(stmts if isinstance(stmts, list) else [stmts])
    return statements


# --- 1. Exactly one S3 bucket, correctly configured ------------------------------------------


def test_exactly_one_s3_bucket(template: Template) -> None:
    template.resource_count_is("AWS::S3::Bucket", 1)


def test_bucket_is_versioned(template: Template) -> None:
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {"VersioningConfiguration": {"Status": "Enabled"}},
    )


def test_bucket_expires_noncurrent_versions_after_30_days(template: Template) -> None:
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "LifecycleConfiguration": {
                "Rules": Match.array_with(
                    [Match.object_like({"NoncurrentVersionExpiration": {"NoncurrentDays": 30}})]
                )
            }
        },
    )


def test_bucket_blocks_all_public_access(template: Template) -> None:
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )


# --- 2. No NAT gateway, no VPC endpoint (spec S9.2: a NAT gateway alone costs more than the
# whole monthly budget) ------------------------------------------------------------------------


def test_no_nat_gateways(template: Template) -> None:
    template.resource_count_is("AWS::EC2::NatGateway", 0)


def test_no_vpc_endpoints(template: Template) -> None:
    template.resource_count_is("AWS::EC2::VPCEndpoint", 0)


# --- 3. One EventBridge schedule, exactly as specified ----------------------------------------


def test_exactly_one_schedule(template: Template) -> None:
    template.resource_count_is("AWS::Scheduler::Schedule", 1)


def test_schedule_is_nightly_at_0300_utc_with_no_flexible_window(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Scheduler::Schedule",
        {
            "ScheduleExpression": "cron(0 3 * * ? *)",
            "ScheduleExpressionTimezone": "UTC",
            "FlexibleTimeWindow": {"Mode": "OFF"},
        },
    )


def test_schedule_never_retries_a_failed_start(template: Template) -> None:
    """A failed start must not trigger a second run the same night (spec S9.1: the store is
    saved once, at the end, by a single task -- a retried second task would be a second
    writer)."""
    template.has_resource_properties(
        "AWS::Scheduler::Schedule",
        {"Target": Match.object_like({"RetryPolicy": {"MaximumRetryAttempts": 0}})},
    )


def test_schedule_assigns_a_public_ip(template: Template) -> None:
    """No NAT gateway (test group 2) means the task's only route to the internet -- the NTSB
    API, S3, ECR, CloudWatch Logs -- is a public IP of its own."""
    template.has_resource_properties(
        "AWS::Scheduler::Schedule",
        {
            "Target": Match.object_like(
                {
                    "EcsParameters": Match.object_like(
                        {
                            "NetworkConfiguration": {
                                "AwsvpcConfiguration": Match.object_like(
                                    {"AssignPublicIp": "ENABLED"}
                                )
                            }
                        }
                    )
                }
            )
        },
    )


# --- 4. Task definition: the secret, and the 90-minute wrapper --------------------------------


def test_task_definition_secret_references_the_api_key_parameter(template: Template) -> None:
    """The parameter's ARN is built at deploy time from `AWS::Partition`/`AWS::AccountId`
    tokens (`Fn::Join`), not a literal string, so this reads the raw template rather than
    fighting `Match.string_like_regexp` over an unresolved intrinsic."""
    resources = template.find_resources("AWS::ECS::TaskDefinition")
    (task_definition,) = resources.values()
    (container,) = task_definition["Properties"]["ContainerDefinitions"]
    (secret,) = container["Secrets"]
    assert secret["Name"] == "NTSB_API_KEY"
    join_parts = secret["ValueFrom"]["Fn::Join"][1]
    assert join_parts[-1].endswith(":parameter/ntsb/api-key")


def test_task_entry_point_wraps_the_program_in_the_90_minute_timeout(template: Template) -> None:
    """EventBridge Scheduler has no way to stop a running ECS task, so the 90-minute limit
    (spec S9.1/S9.2) has to be enforced inside the container itself (controller note 1): `timeout`
    sends SIGTERM at 5400 seconds (90 minutes) and SIGKILL 60 seconds after that if the process
    has not exited, so a run that hits the limit dies before its final S3 upload rather than
    writing something partial."""
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": Match.array_with(
                [
                    Match.object_like(
                        {
                            "EntryPoint": [
                                "timeout",
                                "--signal=TERM",
                                "--kill-after=60",
                                "5400",
                                "ntsb-record",
                            ],
                            "Command": ["run"],
                        }
                    )
                ]
            )
        },
    )


def test_task_container_does_not_use_a_readonly_root_filesystem(template: Template) -> None:
    """Carried from Task 12: the recorder writes its docket cache, and a local store's SQLite
    file, under `/tmp/ntsb` at runtime -- a read-only root filesystem with no volume mounted
    there would fail on the container's first write."""
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": Match.array_with(
                [Match.object_like({"ReadonlyRootFilesystem": False})]
            )
        },
    )


def test_task_definition_is_the_smallest_fargate_size(template: Template) -> None:
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {"Cpu": "256", "Memory": "512", "RequiresCompatibilities": ["FARGATE"]},
    )


# --- 5. ECR repository: MUTABLE tags, keep-5 lifecycle -----------------------------------------


def test_exactly_one_ecr_repository(template: Template) -> None:
    template.resource_count_is("AWS::ECR::Repository", 1)


def test_ecr_repository_stays_tag_mutable(template: Template) -> None:
    """Carried from Task 12: `image-push` re-pushes `:latest` on every merge to `main`. An
    IMMUTABLE repository would reject the second push of that tag, and every image after the
    first would fail to publish."""
    template.has_resource_properties(
        "AWS::ECR::Repository",
        {"ImageTagMutability": "MUTABLE"},
    )


def test_ecr_repository_keeps_only_the_5_newest_images(template: Template) -> None:
    resources = template.find_resources("AWS::ECR::Repository")
    (repository,) = resources.values()
    policy = json.loads(repository["Properties"]["LifecyclePolicy"]["LifecyclePolicyText"])
    rules = policy["rules"]
    assert any(
        rule["selection"].get("countType") == "imageCountMoreThan"
        and rule["selection"].get("countNumber") == 5
        and rule["action"]["type"] == "expire"
        for rule in rules
    ), rules


# --- 6. The deploy role's trust condition -------------------------------------------------------


def test_deploy_role_trust_names_the_repository_and_branch(template: Template) -> None:
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": Match.object_like(
                {
                    "Statement": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "Action": "sts:AssumeRoleWithWebIdentity",
                                    "Condition": {
                                        "StringEquals": {
                                            "token.actions.githubusercontent.com:aud": (
                                                "sts.amazonaws.com"
                                            ),
                                            "token.actions.githubusercontent.com:sub": (
                                                "repo:floyda/ntsb-probable-cause:"
                                                "ref:refs/heads/main"
                                            ),
                                        }
                                    },
                                }
                            )
                        ]
                    )
                }
            )
        },
    )


def test_stack_synths_when_importing_an_existing_oidc_provider() -> None:
    """An account may hold only one `token.actions.githubusercontent.com` provider; passing
    its ARN as context must import it rather than try to create a second one. This is also the
    "offline" path exercised end to end: no AWS call is made either way (controller note 2)."""
    existing_arn = f"arn:aws:iam::{_TEST_ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"
    imported = _build_template(github_oidc_provider_arn=existing_arn)
    imported.resource_count_is("Custom::AWSCDKOpenIdConnectProvider", 0)
    # Task role, execution role, scheduler role, deploy role -- one fewer than the
    # default (creating) path, which also creates the custom resource's own service role.
    imported.resource_count_is("AWS::IAM::Role", 4)


# --- 7. No bare wildcards, with three stated, narrow exceptions ---------------------------------

# `ecr:GetAuthorizationToken` has no resource-level permissions at all -- AWS requires
# `Resource: "*"` for it; it only returns a short-lived registry login token, not access to any
# repository's images. `kms:Decrypt` on the AWS-managed `alias/aws/ssm` key is the same shape of
# exception for a different reason: an account's managed key ID is not knowable without a live
# lookup, which would break offline `cdk synth` (controller note 2), so the policy uses
# `Resource: "*"` narrowed by the `kms:ResourceAliases` condition key to that one alias instead
# of a key ARN.
#
# The five `iam:*OpenIDConnectProvider*` actions are not code this stack wrote: CDK generates
# them, on the Lambda execution role of the custom resource it creates to manage the GitHub
# OIDC provider (only in the default, provider-creating path -- gone entirely when
# `github_oidc_provider_arn` imports an existing one instead, as the test above shows by its
# role count). They have the same "resource does not exist yet at grant time" shape as
# `ecr:GetAuthorizationToken`: an OIDC provider's ARN cannot be named in a policy before the
# provider is created. Listed here, as the test brief asked, rather than silently allowed.
_ALLOWED_WILDCARD_ACTIONS = {"ecr:GetAuthorizationToken", "kms:Decrypt"}
_CDK_GENERATED_OIDC_CUSTOM_RESOURCE_ACTIONS = {
    "iam:CreateOpenIDConnectProvider",
    "iam:DeleteOpenIDConnectProvider",
    "iam:UpdateOpenIDConnectProviderThumbprint",
    "iam:AddClientIDToOpenIDConnectProvider",
    "iam:RemoveClientIDFromOpenIDConnectProvider",
}


def _actions(statement: dict[str, Any]) -> list[str]:
    action = statement.get("Action", [])
    return action if isinstance(action, list) else [action]


def test_no_policy_statement_allows_every_action(template: Template) -> None:
    offenders = [s for s in _all_policy_statements(template) if "*" in _actions(s)]
    assert offenders == []


def test_no_policy_statement_targets_every_resource_except_the_stated_exceptions(
    template: Template,
) -> None:
    offenders = []
    for statement in _all_policy_statements(template):
        resource = statement.get("Resource")
        resources = resource if isinstance(resource, list) else [resource]
        if "*" not in resources:
            continue
        actions = set(_actions(statement))
        if (
            actions <= _ALLOWED_WILDCARD_ACTIONS
            or actions <= _CDK_GENERATED_OIDC_CUSTOM_RESOURCE_ACTIONS
        ):
            continue
        offenders.append(statement)
    assert offenders == []


def test_kms_decrypt_wildcard_is_narrowed_to_the_one_alias(template: Template) -> None:
    """The one thing test group 7's blanket check above cannot see on its own: that the
    `kms:Decrypt` exception really is narrowed by a condition, not a bare `Resource: "*"`."""
    kms_statements = [s for s in _all_policy_statements(template) if "kms:Decrypt" in _actions(s)]
    assert len(kms_statements) == 1
    (statement,) = kms_statements
    assert statement["Resource"] == "*"
    assert statement["Condition"] == {
        "ForAnyValue:StringEquals": {"kms:ResourceAliases": "alias/aws/ssm"}
    }


# --- 8. Container Insights disabled --------------------------------------------------------------


def test_container_insights_is_disabled(template: Template) -> None:
    template.has_resource_properties(
        "AWS::ECS::Cluster",
        {"ClusterSettings": Match.array_with([{"Name": "containerInsights", "Value": "disabled"}])},
    )


# --- Outputs -----------------------------------------------------------------------------------


def test_outputs_include_bucket_log_group_role_and_repository(template: Template) -> None:
    outputs = template.to_json()["Outputs"]
    names = set(outputs)
    assert {"BucketName", "LogGroupName", "DeployRoleArn", "RepositoryUri"} <= names
