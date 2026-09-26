"""The recorder's AWS stack (S2.5 Task 13, spec S9.2; decisions 0004, 0005, 0010, 0069).

One nightly Fargate task, triggered by EventBridge Scheduler at 03:00 UTC, running the same
container image (`Dockerfile`, Task 12) that runs locally. State is a SQLite file in a
versioned S3 bucket (0004); the NTSB API key comes from AWS Systems Manager Parameter Store,
never from this stack (0069); the region is `eu-west-2`, in a project-only AWS account (0010).

Every resource below carries a one-line comment saying what it is and what it costs
(estimates; spec S9.4 says the billed figures replace them at close-out).

Two constraints carried from Task 12 (fix round 1), not new resources:

- The ECR repository stays tag-**mutable** (CDK's default). CI's `image-push` job
  (`.github/workflows/ci.yml`) re-pushes the `:latest` tag on every merge to `main`; an
  immutable repository would reject that second push and every night after the first image
  would run stale code.
- The task's container does **not** run with a read-only root filesystem. The recorder writes
  its docket cache, and a local store's SQLite file, under `/tmp/ntsb` (`NTSB_DATA_DIR`, set in
  the `Dockerfile`) at runtime; a read-only root with no volume mounted there would fail on the
  first write.

Deployment offline (controller note 2): `cdk synth` must work with no AWS credentials and no
network calls, so the VPC is created fresh here -- never looked up from an existing account.
`app.py` leaves the stack's account unresolved (see its own docstring for why -- in short, a
concrete account is what makes `ec2.Vpc`'s explicit `availability_zones` list trigger a real
AWS lookup rather than a CloudFormation pseudo-parameter, regardless of the list being given
explicitly); `cdk deploy --profile ntsb` resolves the real account from the profile at deploy
time.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, Duration, Environment, Fn, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_ssm as ssm
from constructs import Construct

# The repository this stack's deploy role is trusted for (controller note 3, GitHub OIDC) and
# the branch CI pushes images from. Exact match, not a wildcard: only a merge to `main` in this
# repository can assume the role that can push to ECR.
_GITHUB_REPO_SUBJECT = "repo:floyda/ntsb-probable-cause:ref:refs/heads/main"

# AWS Systems Manager's own name for the parameter Andy writes by hand (0069). The stack only
# ever references this name -- it never creates or holds the value.
_API_KEY_PARAMETER_NAME = "/ntsb/api-key"

# The scheduler's cron expression (spec S9.2): 03:00 UTC every day. EventBridge's cron syntax
# has six fields (minute hour day-of-month month day-of-week year); "?" means "no specific
# value" and is required in exactly one of the day-of-month/day-of-week fields.
_NIGHTLY_CRON = "cron(0 3 * * ? *)"

# The 90-minute limit (spec S9.1/S9.2) has to be enforced inside the task, because EventBridge
# Scheduler has no way to stop a running ECS task (controller note 1). `timeout` (part of
# coreutils, present in the Dockerfile's `bookworm-slim` base) wraps the real entrypoint:
# `--signal=TERM` asks the process to shut down cleanly first; `--kill-after=60` sends SIGKILL
# 60 seconds later if it has not; `5400` is 90 minutes in seconds. A run killed this way dies
# before its final S3 upload, so nothing partial is ever written back (spec S9.1's rule that a
# half-finished night cannot exist) -- the store some other night already holds stays the
# record, and tomorrow's run simply sees a wider interval, never a false date.
_NINETY_MINUTES_SECONDS = "5400"
_TASK_ENTRY_POINT = [
    "timeout",
    "--signal=TERM",
    "--kill-after=60",
    _NINETY_MINUTES_SECONDS,
    "ntsb-record",
]
_TASK_COMMAND = ["run"]

_TASK_FAMILY = "ntsb-recorder"


class NtsbRecorderStack(Stack):
    """The recorder's whole AWS footprint: store, schedule, task, and the CI deploy role."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env: Environment | None = None,
        github_oidc_provider_arn: str | None = None,
    ) -> None:
        """Build the stack.

        Args:
            scope: The CDK app or parent construct.
            construct_id: This stack's construct id.
            env: The account/region this stack deploys to. `app.py` passes the fixed region
                `eu-west-2` and leaves account unset, so `cdk deploy --profile ntsb` resolves
                it from the profile, and `cdk synth` never attempts an account-specific AWS
                lookup regardless of what is set in the calling shell.
            github_oidc_provider_arn: ARN of an *existing* `token.actions.githubusercontent.com`
                OIDC provider in the target account, if the account already has one (an account
                may only have one provider per URL). When unset, this stack creates one. Passed
                as CDK context (`-c github_oidc_provider_arn=<arn>`), never guessed -- the
                runbook tells Andy how to check first.
        """
        super().__init__(scope, construct_id, env=env)

        # 1. S3 bucket -- the file store. Holds `recorder.sqlite`. Versioned, so every night's
        # upload is kept as a version; old versions expire after 30 days, otherwise they would
        # grow by about 3.6 GB a year (spec S9.2 estimate). Blocks all public access; requires
        # TLS; kept on `cdk destroy` (RETAIN) because it is the recorder's only durable state.
        # Cost: a few cents a month at this size.
        bucket = s3.Bucket(
            self,
            "Store",
            versioned=True,
            lifecycle_rules=[s3.LifecycleRule(noncurrent_version_expiration=Duration.days(30))],
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # 2. Parameter Store reference -- a *reference*, not the value. Andy writes the real key
        # by hand from `pass` (0069, `docs/runbooks/recorder-deploy.md`); this stack never sees
        # it, so it is not in the image, this code, CloudFormation, or git. Free.
        api_key_parameter = ssm.StringParameter.from_secure_string_parameter_attributes(
            self,
            "ApiKeyParameter",
            parameter_name=_API_KEY_PARAMETER_NAME,
        )

        # 3. VPC -- public subnets only, no NAT gateway. A NAT gateway costs about $35/month on
        # its own, more than the project's whole $30/month budget (spec S9.2); the task needs
        # outbound internet (the NTSB API, S3, ECR, CloudWatch Logs) and nothing needs to reach
        # it, so a public subnet with `assign_public_ip=ENABLED` gets outbound access for free.
        # No interface or gateway VPC endpoints either -- each one is itself a billed resource,
        # and this stack has nothing that benefits from one at this size.
        #
        # `availability_zones=[...]`, not `max_azs=2`: `max_azs` makes CDK look up the real
        # list of AZs for the deploying account and region, which can write the answer to
        # `infra/cdk.context.json` -- a file that would then carry the account's own AZ names
        # on disk (now gitignored regardless, as defence in depth). `eu-west-2a`/`eu-west-2b`
        # are London's first two AZs, always present (a region with only one AZ does not
        # exist), so naming them directly is deterministic and needs no lookup to choose.
        #
        # This alone is not sufficient, though, and it is worth being exact about why: `Vpc`
        # still reads `Stack.availabilityZones` internally to validate the given list against
        # the stack's real AZs, and that property attempts a live, credentialed lookup the
        # moment the stack's *account* is concrete -- independent of whether `availability_zones`
        # was given explicitly (confirmed directly against `aws-cdk-lib`'s own source; passing
        # this list changes nothing about whether the lookup is attempted, only what CDK does
        # with the result if it succeeds). What actually keeps `cdk synth` lookup-free is
        # `app.py` leaving the stack's account unresolved -- see its docstring.
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

        # No inbound rules are added below, so nothing on the internet can reach the task;
        # `allow_all_outbound` covers the NTSB API, S3, ECR and CloudWatch Logs calls it makes.
        # Cost: free -- a security group has no charge of its own.
        task_security_group = ec2.SecurityGroup(
            self,
            "TaskSecurityGroup",
            vpc=vpc,
            description="Recorder task: no inbound access, all outbound access.",
            allow_all_outbound=True,
        )

        # 4. ECR repository, ECS cluster, log group and task definition -- everything the
        # container itself needs. First, the ECR repository: the image registry. Tag
        # mutability stays at its CDK default, `MUTABLE` (the carried constraint above); a
        # lifecycle rule keeps only the 5 newest images, so storage cost does not grow forever;
        # `image_scan_on_push` is the free basic vulnerability scan. Kept on `cdk destroy`
        # (RETAIN), so a re-deploy never loses the images CI already pushed. Cost: a few cents
        # a month.
        repository = ecr.Repository(
            self,
            "Repository",
            repository_name="ntsb-recorder",
            image_tag_mutability=ecr.TagMutability.MUTABLE,
            image_scan_on_push=True,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=5)],
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ECS cluster -- just a namespace for the task; nothing runs continuously. Container
        # Insights is off: it bills per metric and this project has no use for it at one task a
        # night. Named explicitly (the same fixed name as the task family below), rather than
        # left to CDK's generated name, so the runbook's one-off manual run
        # (`docs/runbooks/recorder-deploy.md`) can say `--cluster ntsb-recorder` outright
        # instead of looking the name up first.
        cluster = ecs.Cluster(
            self,
            "Cluster",
            cluster_name=_TASK_FAMILY,
            vpc=vpc,
            container_insights_v2=ecs.ContainerInsights.DISABLED,
        )

        # CloudWatch Logs -- one line per case per side, kept 30 days (spec S9.1). Named
        # explicitly so the runbook can point Andy at an exact console path, and its own output
        # below.
        log_group = logs.LogGroup(
            self,
            "TaskLogGroup",
            log_group_name="/ecs/ntsb-recorder",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Fargate task definition -- the smallest size (256 CPU units / 512 MB memory), the
        # smallest Fargate offers. `readonly_root_filesystem=False` on the container below is
        # the second carried constraint: the recorder writes `/tmp/ntsb` at runtime.
        task_definition = ecs.FargateTaskDefinition(
            self,
            "TaskDefinition",
            family=_TASK_FAMILY,
            cpu=256,
            memory_limit_mib=512,
        )

        # The task role -- what the *running program* is allowed to do. `store/sync.py` only
        # ever calls `download_file` (a `GetObject`) and `upload_file` (a `PutObject`) on this
        # one object -- never deletes anything -- so the role gets `grant_read` + `grant_put`,
        # not the broader `grant_read_write` (which also includes `s3:DeleteObject*`). Keeping
        # delete out of the task role's reach is what makes the bucket's own versioning (above)
        # a real safety net: a bug in the recorder can overwrite `recorder.sqlite` with a bad
        # night's data, recoverable from a prior version, but it cannot delete the version
        # history itself.
        bucket.grant_read(task_definition.task_role)
        bucket.grant_put(task_definition.task_role)

        # The execution role -- what *Fargate itself* does before the program starts: pull the
        # image and inject the secret. `secrets=` below makes CDK grant it `ssm:GetParameters`
        # on this one parameter automatically, which is all it needs: the parameter is a
        # `SecureString`, but 0069's command passes no `--key-id`, so SSM encrypts it with the
        # *default* AWS-managed key (`alias/aws/ssm`) -- and per the ECS Developer Guide
        # ("Retrieve secrets through Secrets Manager or Systems Manager Parameter Store",
        # `task_execution_IAM_role.html#task-execution-secrets`), `kms:Decrypt` is required
        # "only if your secret uses a customer managed key and not the default key". No KMS
        # grant is added here (see the corrected Deviation entry for the earlier, wrong version
        # of this comment, which added one).
        #
        # `obtain_execution_role()` (not the `.execution_role` property, which stays `None`
        # until something else asks for the role first) creates the role now, so the
        # `iam:PassRole` grant below (Fargate assuming it to start the task) targets the same
        # role object CDK actually creates, not a second, separately lazily-created one.
        execution_role = task_definition.obtain_execution_role()

        # `add_container` builds the container definition and attaches it to `task_definition`
        # in place; nothing further needs the return value, since the scheduler target below
        # references `task_definition` itself.
        task_definition.add_container(
            "recorder",
            image=ecs.ContainerImage.from_ecr_repository(repository, tag="latest"),
            entry_point=_TASK_ENTRY_POINT,
            command=_TASK_COMMAND,
            environment={"NTSB_STORE": f"s3://{bucket.bucket_name}/recorder.sqlite"},
            secrets={"NTSB_API_KEY": ecs.Secret.from_ssm_parameter(api_key_parameter)},
            logging=ecs.LogDrivers.aws_logs(stream_prefix="recorder", log_group=log_group),
            readonly_root_filesystem=False,
        )

        # 5. EventBridge Scheduler -- the alarm clock. Runs the task once a night, 03:00 UTC,
        # with no flexible window (an exact time, not a window CloudWatch may shift). Free at
        # this volume (one invocation a day).
        scheduler_role = iam.Role(
            self,
            "SchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        task_definition_family_arn = (
            f"arn:aws:ecs:{self.region}:{self.account}:task-definition/{_TASK_FAMILY}:*"
        )
        # `ecs:RunTask` on the task definition *family* (every revision), not one pinned
        # revision -- each `cdk deploy` that changes the container spec creates a new revision,
        # and the schedule must keep working without a stack update every time that happens.
        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask"],
                resources=[task_definition_family_arn],
            )
        )
        # Fargate assumes the task's own two roles when it starts the container; the scheduler
        # role needs `iam:PassRole` to hand them over, and only these two -- not `iam:PassRole`
        # on every role in the account.
        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[
                    task_definition.task_role.role_arn,
                    execution_role.role_arn,
                ],
            )
        )

        public_subnet_ids = [subnet.subnet_id for subnet in vpc.public_subnets]
        scheduler.CfnSchedule(
            self,
            "NightlySchedule",
            schedule_expression=_NIGHTLY_CRON,
            schedule_expression_timezone="UTC",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=cluster.cluster_arn,
                role_arn=scheduler_role.role_arn,
                # A Scheduler retry only fires when the `RunTask` API call itself failed (for
                # example, throttled) -- in that case no task ever started, so a retry cannot
                # produce two tasks writing to the store the same night (spec S9.1's single-
                # writer rule is about the *task* succeeding twice, not the schedule invocation
                # failing once). Reversed from this stack's first version, which set
                # `maximum_retry_attempts=0` on the mistaken assumption that any retry risked a
                # second writer -- see the dated Deviation entry that corrects it.
                # `maximum_event_age_in_seconds=3600` bounds how long a retry is still worth
                # attempting -- an hour after the scheduled 03:00 UTC start, so the latest a
                # retried task can actually *start* is about 04:00 UTC; from there it can still
                # run the full 90 minutes plus the 60-second kill grace (the `timeout` wrapper
                # above), so the true end of "the night's run" the runbook treats as its
                # exclusion window is about 05:31 UTC, not 04:30.
                retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(
                    maximum_retry_attempts=2,
                    maximum_event_age_in_seconds=3600,
                ),
                ecs_parameters=scheduler.CfnSchedule.EcsParametersProperty(
                    task_definition_arn=task_definition.task_definition_arn,
                    launch_type="FARGATE",
                    network_configuration=scheduler.CfnSchedule.NetworkConfigurationProperty(
                        awsvpc_configuration=scheduler.CfnSchedule.AwsVpcConfigurationProperty(
                            subnets=public_subnet_ids,
                            security_groups=[task_security_group.security_group_id],
                            assign_public_ip="ENABLED",
                        )
                    ),
                ),
            ),
        )

        # 6. GitHub OIDC -- lets GitHub Actions push images without a stored AWS secret. An
        # account may hold only one provider per URL, so this stack imports an existing one
        # when told to (`github_oidc_provider_arn`, checked by the runbook with
        # `aws iam list-open-id-connect-providers`) rather than risk a duplicate-provider
        # deploy failure. Free.
        #
        # `iam.OidcProviderNative` (added in aws-cdk-lib 2.163, present in the 2.270.0 pinned
        # here), not the older `iam.OpenIdConnectProvider`: the native construct synthesizes
        # the real `AWS::IAM::OIDCProvider` CloudFormation resource type directly, whereas the
        # older one (when creating a new provider, as opposed to importing one) synthesizes a
        # Lambda-backed custom resource to manage it instead -- its own IAM role with a
        # `Resource: "*"` policy for the `iam:*OpenIDConnectProvider*` actions, an asset bucket
        # entry, and a log group with no retention set. The native resource needs none of that
        # extra machinery and creates no extra resources at all.
        oidc_provider = (
            iam.OidcProviderNative.from_oidc_provider_arn(
                self, "GithubOidcProvider", github_oidc_provider_arn
            )
            if github_oidc_provider_arn
            else iam.OidcProviderNative(
                self,
                "GithubOidcProvider",
                url="https://token.actions.githubusercontent.com",
                client_ids=["sts.amazonaws.com"],
            )
        )

        # The deploy role CI assumes. Trust is limited to one exact subject -- this repository,
        # pushes to `main` only -- so a pull request (which could come from a fork) can never
        # assume it; `image-push` already restricts itself the same way independently
        # (`.github/workflows/ci.yml`), and this is the actual enforcement.
        deploy_role = iam.Role(
            self,
            "GithubDeployRole",
            assumed_by=iam.WebIdentityPrincipal(
                oidc_provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                        "token.actions.githubusercontent.com:sub": _GITHUB_REPO_SUBJECT,
                    }
                },
            ),
        )
        # `ecr:GetAuthorizationToken` has no resource-level permissions -- AWS requires it be
        # granted on `*`; it only returns a short-lived login token, not access to any
        # repository's images.
        deploy_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],
            )
        )
        # Push and pull, scoped to this one repository -- nothing else.
        repository.grant_pull_push(deploy_role)

        # 7. Outputs -- what the runbook and CI need. `SubnetIds` and `SecurityGroupId` are not
        # in the brief's original four -- added so the runbook's manual `aws ecs run-task`
        # step (`docs/runbooks/recorder-deploy.md`) can read the network configuration straight
        # from `describe-stacks`, rather than a separate `describe-stack-resources` lookup by
        # resource type.
        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "LogGroupName", value=log_group.log_group_name)
        CfnOutput(self, "DeployRoleArn", value=deploy_role.role_arn)
        CfnOutput(self, "RepositoryUri", value=repository.repository_uri)
        CfnOutput(self, "SubnetIds", value=Fn.join(",", public_subnet_ids))
        CfnOutput(self, "SecurityGroupId", value=task_security_group.security_group_id)
