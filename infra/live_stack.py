"""The live night's AWS stack (S4 Task 12, decisions 0171, 0172, 0177, 0178; spec S4 4.1).

One scheduled Fargate task, from the same `Dockerfile` as the recorder's, with its own network,
image repository, result bucket, alert topic, missed-night alarm and the ledger's GitHub role.
The recorder's stack is not touched. Andy runs every `cdk deploy`; the schedule is deployed
`DISABLED` and enabling it (`-c live_schedule=enabled`) is the go-ahead for the first night.

The image is pinned by digest (`live_image_digest`, printed by `scripts/build_live_image.sh`).
The `Dockerfile` already bakes in `NTSB_COMMIT_SHA` (build-arg `COMMIT_SHA`), `NTSB_DATA_DIR`
(`/tmp/ntsb`, writable) and the `aws` extra, and its entry point is `ntsb-record`; so this task
overrides the *entry point* (not just the command) with
`timeout --signal=TERM --kill-after=60 10800 ntsb-live` and gives the command `run`, so the
container's argv is `timeout --signal=TERM --kill-after=60 10800 ntsb-live run`.

Alarm limits, checked on AWS's PutMetricAlarm API reference
(https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_PutMetricAlarm.html,
read 2026-10-11): a period is 10, 20, 30 or a multiple of 60 seconds; `EvaluationPeriods` has
a minimum of 1; "Period multiplied by EvaluationPeriods can't be more than 604,800 seconds"
(seven days), and only periods under one hour are limited to one day. Six hours times five
periods is 30 hours, inside both limits.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from aws_cdk import CfnOutput, Duration, Environment, Fn, RemovalPolicy, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from aws_cdk import aws_ssm as ssm
from constructs import Construct

# The OIDC subject GitHub sends for this repository, in GitHub's immutable form: the owner and
# the repository by name and numeric id. The repository's OIDC setting has
# `use_immutable_subject: true`; this prints the prefix:
#   gh api repos/floyda/ntsb-probable-cause/actions/oidc/customization/sub
# A role that trusts only `repo:floyda/ntsb-probable-cause:...` is refused (the first ledger run,
# 2026-10-12). The ids also stop a deleted and re-created repository of the same name from taking
# the role.
GITHUB_SUBJECT_PREFIX = "repo:floyda@2824846/ntsb-probable-cause@1367368639"
DEFAULT_LEDGER_BRANCHES = ("main",)
PLACEHOLDER_DIGEST = "sha256:" + "0" * 64
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")  # an image digest, nothing else (A14)

_FAMILY = "ntsb-live"
_TIMEOUT_SECONDS = "10800"  # 3 hours; the recorder's wrapper is 90 minutes
_ENTRY_POINT = ["timeout", "--signal=TERM", "--kill-after=60", _TIMEOUT_SECONDS, "ntsb-live"]
_COMMAND = ["run"]
_NIGHTLY_CRON = "cron(0 6 * * ? *)"
_METRIC_NAMESPACE = "Ntsb/Live"
_METRIC_NAME = "NightFinished"
_NTSB_KEY_PARAMETER = "/ntsb/api-key"
_OPENROUTER_KEY_PARAMETER = "/ntsb/live/openrouter-key"


class NtsbLiveStack(Stack):
    """The live night's whole AWS footprint."""

    def __init__(  # noqa: PLR0913 -- one keyword per CDK context value
        self,
        scope: Construct,
        construct_id: str,
        *,
        env: Environment | None = None,
        recorder_bucket: str,
        alert_email: str,
        github_oidc_provider_arn: str,
        image_digest: str | None = None,
        allow_placeholder_digest: bool = False,
        schedule_enabled: bool = False,
        ledger_branches: Sequence[str] = DEFAULT_LEDGER_BRANCHES,
    ) -> None:
        """Build the stack.

        Args:
            scope: The CDK app.
            construct_id: This stack's id.
            env: Region (account left unset, as `app.py` explains).
            recorder_bucket: Name of the recorder's bucket; the task reads only
                `recorder.sqlite` from it.
            alert_email: Where the alert topic emails; Andy confirms the subscription.
            github_oidc_provider_arn: The account's existing GitHub OIDC provider (never created).
            image_digest: `sha256:...` of the pushed image; required unless the placeholder is
                allowed (tests and `cdk synth` checks only).
            allow_placeholder_digest: Use a zero digest when none is given.
            schedule_enabled: True makes the schedule `ENABLED`; default `DISABLED`.
            ledger_branches: Branches whose workflows may assume the ledger role.

        Raises:
            ValueError: No digest was given and the placeholder was not allowed, a digest is not
                `sha256:` and 64 lower-case hex characters, or the schedule was enabled with no
                digest or with the placeholder digest given explicitly.
        """
        super().__init__(scope, construct_id, env=env)
        if image_digest is not None and not DIGEST_PATTERN.fullmatch(image_digest):
            raise ValueError(
                "live_image_digest must be sha256: and 64 lower-case hex characters, as "
                "scripts/build_live_image.sh prints it"
            )
        if schedule_enabled and image_digest in {None, PLACEHOLDER_DIGEST}:
            raise ValueError(
                "live_schedule=enabled needs a real live_image_digest, not the placeholder"
            )
        if image_digest is None:
            if not allow_placeholder_digest:
                raise ValueError(
                    "live_image_digest is required (or live_image_digest_placeholder=1)"
                )
            image_digest = PLACEHOLDER_DIGEST

        # Network: public subnets, no NAT (about $35 a month), no inbound rule. Free.
        vpc = ec2.Vpc(
            self,
            "Vpc",
            nat_gateways=0,
            availability_zones=["eu-west-2a", "eu-west-2b"],
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                ),
            ],
        )
        security_group = ec2.SecurityGroup(
            self,
            "TaskSecurityGroup",
            vpc=vpc,
            description="Live task: no inbound access, all outbound access.",
            allow_all_outbound=True,
        )

        # Immutable tags: an image `live-<sha>` can never be replaced under the same name.
        repository = ecr.Repository(
            self,
            "Repository",
            repository_name="ntsb-live",
            image_tag_mutability=ecr.TagMutability.IMMUTABLE,
            image_scan_on_push=True,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=5)],
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Result bucket. Each reply re-uploads `replies.jsonl`, so versions under `runs/` and
        # `export/` grow and expire after 30 days; `nights/` and `scores/` keep every version.
        # Tamper evidence is the ledger of manifest hashes (0178), not the S3 versions.
        bucket = s3.Bucket(
            self,
            "LiveBucket",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            # S5's rebuild listens for the export's finished mark (final review, wave A, A12).
            event_bridge_enabled=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id=f"expire-old-{prefix}",
                    prefix=f"{prefix}/",
                    noncurrent_version_expiration=Duration.days(30),
                )
                for prefix in ("runs", "export")
            ]
            + [
                # The task cannot abort its own killed uploads (no s3:AbortMultipartUpload).
                s3.LifecycleRule(
                    id="abort-incomplete-uploads",
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                )
            ],
        )

        cluster = ecs.Cluster(
            self,
            "Cluster",
            cluster_name=_FAMILY,
            vpc=vpc,
            container_insights_v2=ecs.ContainerInsights.DISABLED,
        )
        log_group = logs.LogGroup(
            self,
            "TaskLogGroup",
            log_group_name="/ecs/ntsb-live",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.RETAIN,
        )

        topic = sns.Topic(self, "AlertTopic")
        topic.add_subscription(subs.EmailSubscription(alert_email))

        task_definition = ecs.FargateTaskDefinition(
            self,
            "TaskDefinition",
            family=_FAMILY,
            cpu=512,
            memory_limit_mib=1024,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.X86_64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        task_role = task_definition.task_role
        # The task role never holds an `s3:Delete*` (0171): the bucket's versions and the
        # ledger are the record. `PutObject` with `IfNoneMatch` needs only `s3:PutObject`.
        task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"arn:aws:s3:::{recorder_bucket}/recorder.sqlite"],
            )
        )
        task_role.add_to_principal_policy(
            iam.PolicyStatement(actions=["s3:ListBucket"], resources=[bucket.bucket_arn])
        )
        task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[bucket.arn_for_objects("*")],
            )
        )
        task_role.add_to_principal_policy(
            iam.PolicyStatement(actions=["sns:Publish"], resources=[topic.topic_arn])
        )
        task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": _METRIC_NAMESPACE}},
            )
        )

        execution_role = task_definition.obtain_execution_role()
        repository.grant_pull(execution_role)

        def secret(construct_id: str, name: str) -> ecs.Secret:
            parameter = ssm.StringParameter.from_secure_string_parameter_attributes(
                self, construct_id, parameter_name=name
            )
            return ecs.Secret.from_ssm_parameter(parameter)

        task_definition.add_container(
            "live",
            # A digest reference, not a tag: the night runs exactly the reviewed image.
            image=ecs.ContainerImage.from_registry(
                Fn.join("", [repository.repository_uri, "@", image_digest])
            ),
            entry_point=_ENTRY_POINT,
            command=_COMMAND,
            environment={
                "NTSB_LIVE_BUCKET": bucket.bucket_name,
                "NTSB_LIVE_ALERT_TOPIC_ARN": topic.topic_arn,
                "NTSB_STORE": f"s3://{recorder_bucket}/recorder.sqlite",
            },
            secrets={
                "NTSB_API_KEY": secret("NtsbKeyParameter", _NTSB_KEY_PARAMETER),
                "OPENROUTER_API_KEY": secret("OpenRouterKeyParameter", _OPENROUTER_KEY_PARAMETER),
            },
            logging=ecs.LogDrivers.aws_logs(stream_prefix="live", log_group=log_group),
            readonly_root_filesystem=False,
        )

        # The missed-night alarm: no finished night in 30 hours (5 x 6 h), missing data
        # counted as breaching (0177). Limits: see the module docstring.
        alarm = cloudwatch.Alarm(
            self,
            "MissedNight",
            metric=cloudwatch.Metric(
                namespace=_METRIC_NAMESPACE,
                metric_name=_METRIC_NAME,
                statistic="Sum",
                period=Duration.hours(6),
            ),
            threshold=1,
            evaluation_periods=5,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )
        alarm.add_alarm_action(cw_actions.SnsAction(topic))
        # The first finished night sends a recovery email.
        alarm.add_ok_action(cw_actions.SnsAction(topic))

        scheduler_role = iam.Role(
            self, "SchedulerRole", assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com")
        )
        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask"],
                resources=[f"arn:aws:ecs:{self.region}:{self.account}:task-definition/{_FAMILY}:*"],
                conditions={"ArnEquals": {"ecs:cluster": cluster.cluster_arn}},
            )
        )
        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[task_role.role_arn, execution_role.role_arn],
            )
        )
        scheduler.CfnSchedule(
            self,
            "Nightly",
            schedule_expression=_NIGHTLY_CRON,
            schedule_expression_timezone="UTC",
            state="ENABLED" if schedule_enabled else "DISABLED",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=cluster.cluster_arn,
                role_arn=scheduler_role.role_arn,
                # No retries: a second start the same day stops at the night's marker anyway.
                retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(
                    maximum_retry_attempts=0, maximum_event_age_in_seconds=60
                ),
                ecs_parameters=scheduler.CfnSchedule.EcsParametersProperty(
                    task_definition_arn=task_definition.task_definition_arn,
                    launch_type="FARGATE",
                    network_configuration=scheduler.CfnSchedule.NetworkConfigurationProperty(
                        awsvpc_configuration=scheduler.CfnSchedule.AwsVpcConfigurationProperty(
                            subnets=[s.subnet_id for s in vpc.public_subnets],
                            security_groups=[security_group.security_group_id],
                            assign_public_ip="ENABLED",
                        )
                    ),
                ),
            ),
        )

        # The ledger's role (0178): GitHub Actions on the listed branches may list the two
        # prefixes and read the manifests, nothing else.
        oidc_provider = iam.OidcProviderNative.from_oidc_provider_arn(
            self, "GithubOidcProvider", github_oidc_provider_arn
        )
        ledger_role = iam.Role(
            self,
            "LedgerRole",
            assumed_by=iam.WebIdentityPrincipal(
                oidc_provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                        "token.actions.githubusercontent.com:sub": [
                            f"{GITHUB_SUBJECT_PREFIX}:ref:refs/heads/{branch}"
                            for branch in ledger_branches
                        ],
                    }
                },
            ),
        )
        ledger_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:ListBucket"],
                resources=[bucket.bucket_arn],
                conditions={
                    "StringLike": {"s3:prefix": ["runs/", "runs/*", "nights/", "nights/*"]}
                },
            )
        )
        ledger_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[
                    bucket.arn_for_objects("runs/*/manifest.json"),
                    bucket.arn_for_objects("nights/*/manifest.json"),
                ],
            )
        )

        CfnOutput(self, "LiveBucketName", value=bucket.bucket_name)
        CfnOutput(self, "RepositoryUri", value=repository.repository_uri)
        CfnOutput(self, "AlertTopicArn", value=topic.topic_arn)
        CfnOutput(self, "LedgerRoleArn", value=ledger_role.role_arn)
        CfnOutput(self, "LogGroupName", value=log_group.log_group_name)
