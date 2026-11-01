"""``infra/live_stack.py``, the live night's AWS stack (S4 Task 12, decisions 0171, 0177, 0178).

Skipped without Node.js, like ``test_infra_stack.py``; the template is built once per module.
"""

import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

if shutil.which("node") is None:
    pytest.skip("aws-cdk-lib needs Node.js (via jsii); none found", allow_module_level=True)

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "infra"))
from live_stack import NtsbLiveStack

_PROVIDER = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"


def _build(*, enabled: bool = False, digest: str | None = None) -> Template:
    app = cdk.App()
    stack = NtsbLiveStack(
        app,
        "TestLive",
        env=cdk.Environment(account="123456789012", region="eu-west-2"),
        recorder_bucket="recorder-bucket-example",
        alert_email="example@example.com",
        github_oidc_provider_arn=_PROVIDER,
        image_digest=digest,
        allow_placeholder_digest=digest is None,
        schedule_enabled=enabled,
    )
    return Template.from_stack(stack)


@pytest.fixture(scope="module")
def tpl() -> Template:
    return _build()


def _statements(tpl: Template, role_prefix: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for policy in tpl.find_resources("AWS::IAM::Policy").values():
        roles = policy["Properties"]["Roles"]
        if any(role_prefix in str(role) for role in roles):
            out.extend(policy["Properties"]["PolicyDocument"]["Statement"])
    return out


def _actions(statement: dict[str, Any]) -> list[str]:
    actions = statement["Action"]
    return [actions] if isinstance(actions, str) else list(actions)


def test_no_nat_gateway_and_two_public_subnets(tpl: Template) -> None:
    tpl.resource_count_is("AWS::EC2::NatGateway", 0)
    tpl.resource_count_is("AWS::EC2::Subnet", 2)
    tpl.has_resource_properties("AWS::EC2::SecurityGroup", {"SecurityGroupIngress": Match.absent()})


def test_repository_is_immutable_and_scanned(tpl: Template) -> None:
    tpl.has_resource_properties(
        "AWS::ECR::Repository",
        {
            "RepositoryName": "ntsb-live",
            "ImageTagMutability": "IMMUTABLE",
            "ImageScanningConfiguration": {"ScanOnPush": True},
        },
    )
    tpl.has_resource("AWS::ECR::Repository", {"DeletionPolicy": "Retain"})


def test_bucket_is_private_versioned_encrypted_and_retained(tpl: Template) -> None:
    tpl.has_resource(
        "AWS::S3::Bucket",
        {
            "DeletionPolicy": "Retain",
            "Properties": {
                "VersioningConfiguration": {"Status": "Enabled"},
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                },
                "BucketEncryption": Match.any_value(),
            },
        },
    )
    tpl.has_resource_properties(
        "AWS::S3::BucketPolicy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [Match.object_like({"Condition": {"Bool": {"aws:SecureTransport": "false"}}})]
                )
            }
        },
    )


def test_noncurrent_versions_expire_under_runs_and_export_only(tpl: Template) -> None:
    (bucket,) = tpl.find_resources("AWS::S3::Bucket").values()
    rules = bucket["Properties"]["LifecycleConfiguration"]["Rules"]
    versioned = [r for r in rules if "NoncurrentVersionExpiration" in r]
    assert {r["Prefix"] for r in versioned} == {"runs/", "export/"}
    (abort,) = [r for r in rules if "AbortIncompleteMultipartUpload" in r]
    assert abort["AbortIncompleteMultipartUpload"] == {"DaysAfterInitiation": 7}
    assert "NoncurrentVersionExpiration" not in abort
    for rule in rules:
        assert rule["Status"] == "Enabled"
    for rule in versioned:
        assert rule["NoncurrentVersionExpiration"] == {"NoncurrentDays": 30}
        assert "ExpirationInDays" not in rule


def test_cluster_log_group_and_task_definition(tpl: Template) -> None:
    tpl.has_resource_properties("AWS::ECS::Cluster", {"ClusterName": "ntsb-live"})
    tpl.has_resource_properties(
        "AWS::Logs::LogGroup", {"LogGroupName": "/ecs/ntsb-live", "RetentionInDays": 30}
    )
    tpl.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "Family": "ntsb-live",
            "Cpu": "512",
            "Memory": "4096",  # decision 0217: a 1.1 GB scan outgrew 1 GB
            "RuntimePlatform": {"CpuArchitecture": "X86_64", "OperatingSystemFamily": "LINUX"},
        },
    )


def _container(tpl: Template) -> dict[str, Any]:
    (task,) = tpl.find_resources("AWS::ECS::TaskDefinition").values()
    (container,) = task["Properties"]["ContainerDefinitions"]
    assert isinstance(container, dict)
    return container


def test_container_argv_is_timeout_ntsb_live_run(tpl: Template) -> None:
    container = _container(tpl)
    # The image's ENTRYPOINT is `ntsb-record`, so the entry point is overridden too.
    assert container["EntryPoint"] + container["Command"] == [
        "timeout",
        "--signal=TERM",
        "--kill-after=60",
        "10800",
        "ntsb-live",
        "run",
    ]


def test_container_image_is_pinned_by_digest(tpl: Template) -> None:
    image = _container(tpl)["Image"]
    assert image["Fn::Join"][1][-1] == "@sha256:" + "0" * 64
    real = "sha256:" + "ab" * 32
    assert real in str(_container(_build(digest=real)))
    assert "latest" not in str(image)


def test_missing_digest_is_refused_without_the_placeholder() -> None:
    with pytest.raises(ValueError, match="live_image_digest"):
        NtsbLiveStack(
            cdk.App(),
            "NoDigest",
            recorder_bucket="r",
            alert_email="a@example.com",
            github_oidc_provider_arn=_PROVIDER,
        )


def test_container_environment_and_secrets(tpl: Template) -> None:
    container = _container(tpl)
    env = {e["Name"]: e["Value"] for e in container["Environment"]}
    assert set(env) == {
        "NTSB_LIVE_BUCKET",
        "NTSB_LIVE_ALERT_TOPIC_ARN",
        "NTSB_STORE",
        "PYTHONUNBUFFERED",
    }
    assert env["PYTHONUNBUFFERED"] == "1"  # a killed night still leaves its lines (0217)
    assert env["NTSB_STORE"] == "s3://recorder-bucket-example/recorder.sqlite"
    assert {s["Name"] for s in container["Secrets"]} == {"NTSB_API_KEY", "OPENROUTER_API_KEY"}
    secrets = str(container["Secrets"])
    assert "/ntsb/api-key" in secrets
    assert "/ntsb/live/openrouter-key" in secrets
    tpl_text = str(container)
    assert "NTSB_MONTHLY_BUDGET_USD" not in tpl_text


def test_task_role_reads_one_recorder_object_and_never_deletes(tpl: Template) -> None:
    statements = _statements(tpl, "TaskDefinitionTaskRole")
    assert statements
    for statement in statements:
        assert statement["Effect"] == "Allow"
        assert not any(
            a.lower().startswith(("s3:delete", "s3:*", "*")) for a in _actions(statement)
        )
    recorder = [s for s in statements if "recorder-bucket-example" in str(s["Resource"])]
    assert len(recorder) == 1
    assert _actions(recorder[0]) == ["s3:GetObject"]
    assert recorder[0]["Resource"] == "arn:aws:s3:::recorder-bucket-example/recorder.sqlite"
    live = [s for s in statements if "LiveBucket" in str(s["Resource"])]
    all_live = {a for s in live for a in _actions(s)}
    assert all_live == {"s3:ListBucket", "s3:GetObject", "s3:PutObject"}
    assert any(
        _actions(s) == ["cloudwatch:PutMetricData"]
        and s["Condition"] == {"StringEquals": {"cloudwatch:namespace": "Ntsb/Live"}}
        for s in statements
    )
    assert any(_actions(s) == ["sns:Publish"] for s in statements)


def test_no_role_anywhere_can_delete_from_s3(tpl: Template) -> None:
    for policy in tpl.find_resources("AWS::IAM::Policy").values():
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
            assert not any(a.lower().startswith("s3:delete") for a in _actions(statement))


def test_alert_topic_has_an_email_subscription(tpl: Template) -> None:
    tpl.resource_count_is("AWS::SNS::Topic", 1)
    tpl.has_resource_properties(
        "AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": "example@example.com"}
    )


def test_missed_night_alarm(tpl: Template) -> None:
    tpl.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "Namespace": "Ntsb/Live",
            "MetricName": "NightFinished",
            "Statistic": "Sum",
            "Period": 21600,
            "EvaluationPeriods": 5,
            "Threshold": 1,
            "ComparisonOperator": "LessThanThreshold",
            "TreatMissingData": "breaching",
            "AlarmActions": [{"Ref": Match.any_value()}],
        },
    )


def test_schedule_is_disabled_by_default_and_enabled_by_context(tpl: Template) -> None:
    props = {
        "ScheduleExpression": "cron(0 6 * * ? *)",
        "ScheduleExpressionTimezone": "UTC",
        "State": "DISABLED",
        "Target": Match.object_like(
            {
                "RetryPolicy": Match.object_like({"MaximumRetryAttempts": 0}),
                "EcsParameters": Match.object_like(
                    {
                        "LaunchType": "FARGATE",
                        "NetworkConfiguration": {
                            "AwsvpcConfiguration": Match.object_like({"AssignPublicIp": "ENABLED"})
                        },
                    }
                ),
            }
        ),
    }
    tpl.has_resource_properties("AWS::Scheduler::Schedule", props)
    _build(enabled=True, digest="sha256:" + "ee" * 32).has_resource_properties(
        "AWS::Scheduler::Schedule", {"State": "ENABLED"}
    )


def test_scheduler_role_runs_the_task_and_passes_two_roles(tpl: Template) -> None:
    statements = _statements(tpl, "SchedulerRole")
    run = next(s for s in statements if _actions(s) == ["ecs:RunTask"])
    assert "task-definition/ntsb-live:*" in str(run["Resource"])
    passed = next(s for s in statements if _actions(s) == ["iam:PassRole"])
    assert [
        r["Fn::GetAtt"][0].startswith(("TaskDefinitionTaskRole", "TaskDefinitionExecutionRole"))
        for r in passed["Resource"]
    ] == [True, True]
    assert passed["Resource"][0]["Fn::GetAtt"][0].startswith("TaskDefinitionTaskRole")
    assert passed["Resource"][1]["Fn::GetAtt"][0].startswith("TaskDefinitionExecutionRole")
    assert all(r["Fn::GetAtt"][1] == "Arn" for r in passed["Resource"])
    cluster = run["Condition"]["ArnEquals"]["ecs:cluster"]["Fn::GetAtt"]
    assert cluster[0].startswith("Cluster")
    assert cluster[1] == "Arn"
    assert set(run["Condition"]) == {"ArnEquals"}


def test_ledger_role_trust_and_permissions(tpl: Template) -> None:
    roles = tpl.find_resources("AWS::IAM::Role")
    ledger = next(r for k, r in roles.items() if k.startswith("LedgerRole"))
    (trust,) = ledger["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    assert trust["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert trust["Principal"] == {"Federated": _PROVIDER}
    cond = trust["Condition"]["StringEquals"]
    assert cond["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    assert cond["token.actions.githubusercontent.com:sub"] == [
        "repo:floyda@2824846/ntsb-probable-cause@1367368639:ref:refs/heads/main",
    ]
    statements = _statements(tpl, "LedgerRole")
    assert len(statements) == 2
    listing = next(s for s in statements if _actions(s) == ["s3:ListBucket"])
    assert listing["Condition"] == {
        "StringLike": {"s3:prefix": ["runs/", "runs/*", "nights/", "nights/*"]}
    }
    reading = next(s for s in statements if _actions(s) == ["s3:GetObject"])
    text = str(reading["Resource"])
    assert "runs/*/manifest.json" in text
    assert "nights/*/manifest.json" in text
    assert len(reading["Resource"]) == 2


def test_outputs(tpl: Template) -> None:
    outputs = tpl.to_json()["Outputs"]
    assert set(outputs) == {
        "LiveBucketName",
        "RepositoryUri",
        "AlertTopicArn",
        "LedgerRoleArn",
        "LogGroupName",
    }


def test_missed_night_alarm_also_sends_a_recovery_email(tpl: Template) -> None:
    (alarm,) = tpl.find_resources("AWS::CloudWatch::Alarm").values()
    props = alarm["Properties"]
    assert props["OKActions"] == props["AlarmActions"]
    assert len(props["OKActions"]) == 1


def test_execution_role_reads_two_parameters_and_pulls_one_repository(tpl: Template) -> None:
    statements = _statements(tpl, "TaskDefinitionExecutionRole")
    ssm = [s for s in statements if all(a.startswith("ssm:") for a in _actions(s))]
    names = sorted(s["Resource"]["Fn::Join"][1][-1].split(":parameter")[1] for s in ssm)
    assert names == ["/ntsb/api-key", "/ntsb/live/openrouter-key"]
    pull = [
        s
        for s in statements
        if any(a.startswith("ecr:") and a != "ecr:GetAuthorizationToken" for a in _actions(s))
    ]
    assert len(pull) == 1
    assert pull[0]["Resource"]["Fn::GetAtt"][0].startswith("Repository")


def test_a_real_digest_with_the_schedule_enabled_is_allowed() -> None:
    _build(enabled=True, digest="sha256:" + "cd" * 32)


def test_the_placeholder_digest_with_the_schedule_enabled_is_refused() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        _build(enabled=True)


def test_the_bucket_sends_its_events_to_eventbridge(tpl: Template) -> None:
    """Item A12: S5 rebuilds the site when the export's finished mark lands."""
    tpl.has_resource_properties(
        "Custom::S3BucketNotifications",
        {"NotificationConfiguration": {"EventBridgeConfiguration": {}}},
    )


@pytest.mark.parametrize(
    "digest",
    [
        "sha256:" + "AB" * 32,  # upper case
        "sha256:" + "ab" * 31,  # short
        "ab" * 32,  # no prefix
        "live-abc1234",  # a tag, not a digest
        "sha256:" + "ab" * 32 + "\n",  # a trailing newline
    ],
)
def test_a_digest_of_the_wrong_form_is_refused(digest: str) -> None:
    """Item A14."""
    with pytest.raises(ValueError, match="64 lower-case hex"):
        _build(digest=digest)


def test_the_placeholder_digest_given_explicitly_with_the_schedule_enabled_is_refused() -> None:
    """Item A14: not only an absent digest; the zero digest by value too."""
    from live_stack import PLACEHOLDER_DIGEST  # noqa: PLC0415

    with pytest.raises(ValueError, match="placeholder"):
        _build(enabled=True, digest=PLACEHOLDER_DIGEST)
    _build(digest=PLACEHOLDER_DIGEST)  # with the schedule off it synthesises
