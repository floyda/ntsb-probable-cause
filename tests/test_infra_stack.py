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
# Both of these must follow the sys.path insert above. Importing `app` (fix round 2, N6) is
# safe -- its stack construction and `app.synth()` call live behind `if __name__ ==
# "__main__":`, which a plain `import` never satisfies, so importing it here runs nothing.
import app as recorder_app  # noqa: E402
from recorder_stack import NtsbRecorderStack  # noqa: E402

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


def test_schedule_retries_only_a_failed_invocation_not_a_failed_task(template: Template) -> None:
    """A Scheduler retry only fires when the `RunTask` API call itself failed -- no task ever
    started, so a retry cannot produce a second task writing to the store the same night (spec
    S9.1's single-writer rule). Reversed from this stack's first version, which set
    `maximum_retry_attempts=0` on the mistaken assumption that any retry risked a second
    writer -- see the dated Deviation entry that corrects it."""
    template.has_resource_properties(
        "AWS::Scheduler::Schedule",
        {
            "Target": Match.object_like(
                {
                    "RetryPolicy": {
                        "MaximumRetryAttempts": 2,
                        "MaximumEventAgeInSeconds": 3600,
                    }
                }
            )
        },
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


def test_default_path_creates_exactly_one_native_oidc_provider(template: Template) -> None:
    """`iam.OidcProviderNative` (fix round 1, Minor 1) synthesizes the real
    `AWS::IAM::OIDCProvider` CloudFormation resource type directly -- no Lambda-backed custom
    resource, no extra role, no extra log group."""
    template.resource_count_is("AWS::IAM::OIDCProvider", 1)
    template.resource_count_is("AWS::Lambda::Function", 0)
    template.resource_count_is("AWS::IAM::Role", 4)


def test_stack_synths_when_importing_an_existing_oidc_provider() -> None:
    """An account may hold only one `token.actions.githubusercontent.com` provider; passing
    its ARN as context must import it rather than try to create a second one. This is also the
    "offline" path exercised end to end: no AWS call is made either way (controller note 2)."""
    existing_arn = f"arn:aws:iam::{_TEST_ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"
    imported = _build_template(github_oidc_provider_arn=existing_arn)
    imported.resource_count_is("AWS::IAM::OIDCProvider", 0)
    # Task role, execution role, scheduler role, deploy role -- the same four as the default
    # (creating) path: the native OIDC provider resource creates no role of its own either way.
    imported.resource_count_is("AWS::IAM::Role", 4)


# --- 7. No bare wildcards, with one stated, narrow exception -----------------------------------

# `ecr:GetAuthorizationToken` has no resource-level permissions at all -- AWS requires
# `Resource: "*"` for it; it only returns a short-lived registry login token, not access to any
# repository's images.
#
# There is no `kms:Decrypt` grant anywhere in this stack (fix round 1, Important 1, corrected
# from this stack's first version): the ECS Developer Guide states plainly that it is "required
# only if your secret uses a customer managed key and not the default key", and 0069's
# `put-parameter` command never passes `--key-id`, so the parameter is encrypted with the
# default AWS-managed key. `test_no_kms_grant_exists` below checks this directly.
#
# The native OIDC provider construct (`iam.OidcProviderNative`, fix round 1, Minor 1) also
# removed the other exception this stack used to need: the older `iam.OpenIdConnectProvider`
# generated a Lambda-backed custom resource with its own `Resource: "*"` policy for
# `iam:*OpenIDConnectProvider*` actions; the native resource type creates no such role.
_ALLOWED_WILDCARD_ACTIONS = {"ecr:GetAuthorizationToken"}


def _actions(statement: dict[str, Any]) -> list[str]:
    action = statement.get("Action", [])
    return action if isinstance(action, list) else [action]


def test_no_policy_statement_allows_every_action(template: Template) -> None:
    offenders = [s for s in _all_policy_statements(template) if "*" in _actions(s)]
    assert offenders == []


def test_no_policy_statement_targets_every_resource_except_the_stated_exception(
    template: Template,
) -> None:
    offenders = []
    for statement in _all_policy_statements(template):
        resource = statement.get("Resource")
        resources = resource if isinstance(resource, list) else [resource]
        if "*" not in resources:
            continue
        if set(_actions(statement)) <= _ALLOWED_WILDCARD_ACTIONS:
            continue
        offenders.append(statement)
    assert offenders == []


def test_no_kms_grant_exists(template: Template) -> None:
    """Fix round 1, Important 1: the default AWS-managed key needs no `kms:Decrypt` grant at
    all (see the comment above `_ALLOWED_WILDCARD_ACTIONS`). This is the direct check that the
    earlier, incorrect grant was actually removed, not just moved."""
    kms_statements = [
        s
        for s in _all_policy_statements(template)
        if any(a.startswith("kms:") for a in _actions(s))
    ]
    assert kms_statements == []


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
    assert {
        "BucketName",
        "LogGroupName",
        "DeployRoleArn",
        "RepositoryUri",
        "SubnetIds",
        "SecurityGroupId",
    } <= names


# --- 9. The strongest protective properties (fix round 1, Important 7) -------------------------


def test_bucket_and_repository_have_deletion_policy_retain(template: Template) -> None:
    """The bucket and the ECR repository are the two resources `docs/runbooks/
    recorder-deploy.md` stage 10 says survive `cdk destroy` -- checked here as the actual
    CloudFormation `DeletionPolicy`, not just the CDK-level `removal_policy` prop, since that
    is what really governs what `cdk destroy` does to the resource."""
    as_json = template.to_json()
    for resource_type in ("AWS::S3::Bucket", "AWS::ECR::Repository"):
        (resource,) = [r for r in as_json["Resources"].values() if r["Type"] == resource_type]
        assert resource["DeletionPolicy"] == "Retain", resource_type


def test_log_group_also_has_deletion_policy_retain(template: Template) -> None:
    """Not one of the brief's original two RETAIN resources, but true of this stack as built,
    and `docs/runbooks/recorder-deploy.md` stage 10 says so explicitly -- checked directly so a
    future change to the log group's `removal_policy` cannot silently make the runbook wrong."""
    as_json = template.to_json()
    (log_group,) = [r for r in as_json["Resources"].values() if r["Type"] == "AWS::Logs::LogGroup"]
    assert log_group["DeletionPolicy"] == "Retain"


def test_scheduler_pass_role_is_scoped_to_exactly_the_two_task_roles(template: Template) -> None:
    """Fargate assumes the task's own two roles (task role, execution role) when it starts the
    container; the scheduler's `iam:PassRole` grant must name exactly those two ARNs, not every
    role in the account -- and not merely *some* two ARNs (fix round 2, N5): each is checked to
    be a `Fn::GetAtt` naming the task definition's own task-role and execution-role logical
    resources specifically, found by their construct-id prefix rather than a hard-coded hash
    suffix (which CDK could regenerate on an unrelated change)."""
    role_logical_ids = template.find_resources("AWS::IAM::Role").keys()
    (task_role_id,) = [r for r in role_logical_ids if r.startswith("TaskDefinitionTaskRole")]
    (execution_role_id,) = [
        r for r in role_logical_ids if r.startswith("TaskDefinitionExecutionRole")
    ]

    pass_role_statements = [
        s for s in _all_policy_statements(template) if _actions(s) == ["iam:PassRole"]
    ]
    assert len(pass_role_statements) == 1
    (statement,) = pass_role_statements
    resources = statement["Resource"]
    assert isinstance(resources, list)
    assert len(resources) == 2
    assert {"Fn::GetAtt": [task_role_id, "Arn"]} in resources
    assert {"Fn::GetAtt": [execution_role_id, "Arn"]} in resources


def test_deploy_role_push_actions_are_scoped_to_the_repository_arn(template: Template) -> None:
    """`repository.grant_pull_push` must land on the repository's own ARN, never `Resource:
    "*"` -- the wildcard tests above already forbid a bare `"*"` for these actions, but this
    checks the positive property directly: the resource named is a `Fn::GetAtt` on the ECR
    repository's own logical resource, not some other value."""
    (repository_logical_id,) = template.find_resources("AWS::ECR::Repository").keys()
    push_actions = {
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
    }
    candidates = [s for s in _all_policy_statements(template) if push_actions & set(_actions(s))]
    assert len(candidates) == 1
    (statement,) = candidates
    resource = statement["Resource"]
    assert resource != "*"
    assert resource == {"Fn::GetAtt": [repository_logical_id, "Arn"]}


def test_security_group_has_no_ingress(template: Template) -> None:
    """No inbound rule of any kind -- nothing on the internet can reach the task. Checked two
    ways (fix round 2, N5): no inline `SecurityGroupIngress` property on the group itself, and
    no separate `AWS::EC2::SecurityGroupIngress` resource either -- CDK can express an ingress
    rule either way (the latter when a rule is added after construction, or with
    `disable_inline_rules`), so only checking one would miss the other."""
    (security_group,) = template.find_resources("AWS::EC2::SecurityGroup").values()
    assert "SecurityGroupIngress" not in security_group["Properties"]
    template.resource_count_is("AWS::EC2::SecurityGroupIngress", 0)


def test_app_leaves_the_account_unresolved() -> None:
    """`infra/app.py`'s own environment construction (fix round 2, N6), imported directly --
    safe because `app.py`'s stack construction and `app.synth()` call are guarded behind `if
    __name__ == "__main__":`, which a plain `import` never satisfies. Protects against
    Important 3's fix (fix round 1) being quietly reintroduced, e.g. by reading
    `CDK_DEFAULT_ACCOUNT` back into `env.account` -- if that happened, `stack.environment`
    below would show a concrete account instead of `unknown-account`, and this test would fail
    even though no `cdk synth` call (which alone reproduced the original bug) is involved."""
    stack = NtsbRecorderStack(cdk.App(), "Test", env=recorder_app.deploy_environment())
    assert stack.environment == "aws://unknown-account/eu-west-2"


def test_log_retention_is_30_days(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Logs::LogGroup",
        {"RetentionInDays": 30},
    )


def test_task_role_cannot_delete_objects(template: Template) -> None:
    """Fix round 1, Minor 5: `grant_read` + `grant_put`, not `grant_read_write`, so the task
    role has no `s3:DeleteObject*` action -- keeping delete out of its reach is what makes the
    bucket's versioning a real safety net rather than one a compromised or buggy task could
    also undo."""
    offenders = [
        s
        for s in _all_policy_statements(template)
        if any(a.startswith("s3:DeleteObject") for a in _actions(s))
    ]
    assert offenders == []
