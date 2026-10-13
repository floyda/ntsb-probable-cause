"""The public site's AWS stacks (S5 spec §18.2, §18.3).

Three stacks, because CloudFront takes its certificate only from us-east-1:

- `NtsbSiteDnsStack` (us-east-1): the `demo.floyda.dev` zone. Andy delegates to it once, with
  four NS records in his personal account's `floyda.dev` zone (spec §12 item 15).
- `NtsbSiteEdgeStack` (us-east-1): the exact-name certificate for `ellery.demo.floyda.dev`,
  validated by DNS in that zone, and the AWS WAF web ACL that CloudFront's flat-rate plan
  requires on the distribution (CloudFront developer guide, flat-rate pricing plans,
  "Unsupported features", read 2026-10-12). Deployed after the delegation, so validation can
  complete.
- `NtsbSiteStack` (eu-west-2): the private site bucket, CloudFront with origin access control
  on the flat-rate Free plan, the CodeBuild project that runs `site/scripts/publish.sh`, the
  rules that start it, and an alert topic.

Every resource carries a one-line comment: what it is and what it costs (external prices, AWS
pricing pages, read 2026-10-11; spec §18.3).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from aws_cdk import CfnOutput, Duration, Environment, Fn, RemovalPolicy, Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_pricingplanmanager as pricingplanmanager
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as route53_targets
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct

ZONE_NAME = "demo.floyda.dev"
SITE_DOMAIN = "ellery.demo.floyda.dev"
EXPORT_PREFIX = "export/board-1/"
FINISHED_KEY = "export/board-1/_finished.json"

# Requests one address may make in 5 minutes before WAF blocks it. A visit is roughly 10 to 20
# requests (estimate, spec §18.3), so 600 is about 30 visits in 5 minutes. Blocked requests never
# count against the flat-rate plan's allowance.
_RATE_LIMIT_PER_5_MINUTES = 600

_GITHUB_OWNER = "floyda"
_GITHUB_REPO = "ntsb-probable-cause"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _holding_style_hash() -> str:
    """The CSP hash of the holding page's one inline style (spec §17.4: no 'unsafe-inline')."""
    page = (_REPO_ROOT / "site/holding/index.html").read_text()
    match = re.search(r"<style>(.*?)</style>", page, re.DOTALL)
    if match is None:
        raise ValueError("site/holding/index.html has no <style> block")
    digest = hashlib.sha256(match.group(1).encode()).digest()
    return "'sha256-" + base64.b64encode(digest).decode() + "'"


class NtsbSiteDnsStack(Stack):
    """The `demo.floyda.dev` hosted zone."""

    def __init__(self, scope: Construct, construct_id: str, *, env: Environment) -> None:
        super().__init__(scope, construct_id, env=env, cross_region_references=True)
        # Public hosted zone: $0.50 a month; alias lookups to CloudFront are free.
        self.zone = route53.PublicHostedZone(self, "Zone", zone_name=ZONE_NAME)
        CfnOutput(
            self, "NameServers", value=Fn.join(", ", self.zone.hosted_zone_name_servers or [])
        )


class NtsbSiteEdgeStack(Stack):
    """The certificate CloudFront needs, in us-east-1."""

    def __init__(
        self, scope: Construct, construct_id: str, *, env: Environment, zone: route53.IHostedZone
    ) -> None:
        super().__init__(scope, construct_id, env=env, cross_region_references=True)
        # Public certificate for the one name, renewed automatically: free.
        self.certificate = acm.Certificate(
            self,
            "Certificate",
            domain_name=SITE_DOMAIN,
            validation=acm.CertificateValidation.from_dns(zone),
        )
        # The web ACL the flat-rate plan requires: allow by default, one per-address rate rule.
        # Included in the flat-rate plan (5 rules on Free); without the plan it would bill
        # pay-as-you-go, so the runbook checks the plan is active.
        self.web_acl = wafv2.CfnWebACL(
            self,
            "WebAcl",
            scope="CLOUDFRONT",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=False,
                metric_name="ellerySite",
                sampled_requests_enabled=False,
            ),
            rules=[
                wafv2.CfnWebACL.RuleProperty(
                    name="rate-per-address",
                    priority=0,
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            aggregate_key_type="IP",
                            limit=_RATE_LIMIT_PER_5_MINUTES,
                            evaluation_window_sec=300,
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=False,
                        metric_name="ellerySiteRate",
                        sampled_requests_enabled=False,
                    ),
                )
            ],
        )


class NtsbSiteStack(Stack):
    """The site bucket, CloudFront, the build and its rules."""

    def __init__(  # noqa: PLR0913 -- a stack takes its dependencies as keyword arguments
        self,
        scope: Construct,
        construct_id: str,
        *,
        env: Environment,
        zone: route53.IHostedZone,
        certificate: acm.ICertificate,
        web_acl_arn: str,
        source_branch: str,
        alert_email: str | None,
        live_bucket_name: str | None,
        github_connection_arn: str | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env, cross_region_references=True)

        # The site's files: private, versioned. A few megabytes, inside the flat-rate plan's
        # 5 GB S3 credit: about $0.
        bucket = s3.Bucket(
            self,
            "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            lifecycle_rules=[s3.LifecycleRule(noncurrent_version_expiration=Duration.days(30))],
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Folder addresses to index pages, at the edge: included in the flat-rate plan.
        rewrite = cloudfront.Function(
            self,
            "UrlRewrite",
            code=cloudfront.FunctionCode.from_file(
                file_path=str(Path(__file__).with_name("site_url_rewrite.js"))
            ),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )

        # Security headers. The flat-rate Free plan refuses custom response header rules (deploy
        # of 2026-10-13), so the standard headers come from AWS's managed SecurityHeadersPolicy
        # (HSTS, nosniff, frame options, referrer policy) and the Content-Security-Policy, which
        # allows the site's own files only, is added by a viewer-response function. Both are
        # included in the plan.
        content_security_policy = (
            "default-src 'self'; img-src 'self' data:; "
            f"style-src 'self' {_holding_style_hash()}; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        add_policy = cloudfront.Function(
            self,
            "ContentSecurityPolicy",
            code=cloudfront.FunctionCode.from_inline(
                "function handler(event) {\n"
                "  var response = event.response;\n"
                "  response.headers['content-security-policy'] = "
                f"{{ value: {json.dumps(content_security_policy)} }};\n"
                "  return response;\n"
                "}\n"
            ),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )

        # The distribution: $0 on the flat-rate Free plan (spec §18.3), chosen below.
        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=rewrite, event_type=cloudfront.FunctionEventType.VIEWER_REQUEST
                    ),
                    cloudfront.FunctionAssociation(
                        function=add_policy,
                        event_type=cloudfront.FunctionEventType.VIEWER_RESPONSE,
                    ),
                ],
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
            ),
            domain_names=[SITE_DOMAIN],
            certificate=certificate,
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403, response_http_status=404, response_page_path="/404.html"
                ),
                cloudfront.ErrorResponse(
                    http_status=404, response_http_status=404, response_page_path="/404.html"
                ),
            ],
            minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
            web_acl_id=web_acl_arn,
        )

        # The flat-rate Free plan: $0, no overage charges (spec §18.3). Free subscriptions are
        # active at once. It covers the distribution, the web ACL and the zone, whose DNS the
        # plan includes. AWS::PricingPlanManager::Subscription, read 2026-10-12.
        pricingplanmanager.CfnSubscription(
            self,
            "FlatRatePlan",
            plan_family="CloudFront",
            plan_tier="FREE",
            usage_level="DEFAULT",
            resource_arns=[
                f"arn:{self.partition}:cloudfront::{self.account}:distribution/"
                f"{distribution.distribution_id}",
                web_acl_arn,
                f"arn:{self.partition}:route53:::hostedzone/{zone.hosted_zone_id}",
            ],
        )

        # The site's name, pointing at the distribution: alias lookups are free.
        record_name = SITE_DOMAIN.removesuffix(f".{ZONE_NAME}")
        alias = route53.RecordTarget.from_alias(route53_targets.CloudFrontTarget(distribution))
        route53.ARecord(self, "AliasA", zone=zone, record_name=record_name, target=alias)
        route53.AaaaRecord(self, "AliasAAAA", zone=zone, record_name=record_name, target=alias)

        # Alerts: an email when a build fails. SNS email: free at this volume.
        # The subscription is added only when an address is given on the command line; the
        # topic itself is always there, so the stack keeps one shape (runbook Stage 6).
        topic = sns.Topic(self, "AlertTopic")
        if alert_email:
            topic.add_subscription(subscriptions.EmailSubscription(alert_email))

        # The build: smallest machine, 15-minute limit. 100 free minutes a month; about
        # 60 to 90 used (estimate, spec §18.3): about $0.
        project = codebuild.Project(
            self,
            "Build",
            source=codebuild.Source.git_hub(
                owner=_GITHUB_OWNER,
                repo=_GITHUB_REPO,
                branch_or_ref=source_branch,
                # A push starts a build only through the named connection (below).
                webhook=github_connection_arn is not None,
                # No commit statuses written back to GitHub (review, 2026-10-12).
                report_build_status=False,
                # Anchored: `and_branch_is` writes an unanchored pattern, which would also match
                # a push to, say, `<branch>-old`.
                webhook_filters=(
                    [
                        codebuild.FilterGroup.in_event_of(
                            codebuild.EventAction.PUSH
                        ).and_head_ref_is(f"^refs/heads/{re.escape(source_branch)}$")
                    ]
                    if github_connection_arn is not None
                    else None
                ),
            ),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                compute_type=codebuild.ComputeType.SMALL,
                environment_variables={
                    "SITE_MODE": codebuild.BuildEnvironmentVariable(value="holding"),
                    "SITE_BUCKET": codebuild.BuildEnvironmentVariable(value=bucket.bucket_name),
                    "DISTRIBUTION_ID": codebuild.BuildEnvironmentVariable(
                        value=distribution.distribution_id
                    ),
                },
            ),
            timeout=Duration.minutes(15),
            build_spec=codebuild.BuildSpec.from_object(
                {
                    "version": "0.2",
                    "phases": {"build": {"commands": ["bash site/scripts/publish.sh"]}},
                }
            ),
        )
        if github_connection_arn is not None:
            # GitHub through the connection Andy approved (runbook Stage 5), named on the project
            # itself: the account's default credential was not used for the webhook (first
            # deploy, 2026-10-13). Free.
            cfn_project = project.node.default_child
            if not isinstance(cfn_project, codebuild.CfnProject):
                raise TypeError("the build project has no CfnProject to override")
            cfn_project.add_property_override(
                "Source.Auth", {"Type": "CODECONNECTIONS", "Resource": github_connection_arn}
            )
            # Its own policy, which names no part of the project, so the project can wait for
            # it: CodeBuild checks the role may use the connection as the project is created,
            # and the role's default policy names the project, so it comes after (third
            # deploy, 2026-10-13: "User is not authorized to access connection").
            if project.role is None:
                raise TypeError("the build project has no role")
            connection_policy = iam.Policy(
                self,
                "BuildConnectionPolicy",
                roles=[project.role],
                statements=[
                    iam.PolicyStatement(
                        actions=[
                            "codeconnections:GetConnection",
                            "codeconnections:GetConnectionToken",
                            "codeconnections:UseConnection",
                        ],
                        resources=[github_connection_arn],
                    )
                ],
            )
            cfn_policy = connection_policy.node.default_child
            if not isinstance(cfn_policy, iam.CfnPolicy):
                raise TypeError("the connection policy has no CfnPolicy")
            cfn_project.add_dependency(cfn_policy)

        # The site bucket: list, read, write and delete current files only. Never old versions,
        # retention or legal holds: any push to the branch runs with this role, and the
        # versions are the way back (review, 2026-10-12).
        project.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                resources=[bucket.arn_for_objects("*")],
            )
        )
        project.add_to_role_policy(
            iam.PolicyStatement(actions=["s3:ListBucket"], resources=[bucket.bucket_arn])
        )
        project.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudfront:CreateInvalidation"],
                resources=[
                    f"arn:aws:cloudfront::{self.account}:distribution/{distribution.distribution_id}"
                ],
            )
        )
        project.on_build_failed("BuildFailed", target=targets.SnsTopic(topic))

        if live_bucket_name is not None:
            # S4's export: read the export folder only (spec §22). Not runs/, scores/, nights/.
            project.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["s3:GetObject"],
                    resources=[f"arn:aws:s3:::{live_bucket_name}/{EXPORT_PREFIX}*"],
                )
            )
            project.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["s3:ListBucket"],
                    resources=[f"arn:aws:s3:::{live_bucket_name}"],
                    conditions={"StringLike": {"s3:prefix": [f"{EXPORT_PREFIX}*"]}},
                )
            )
            # S4's finished mark starts a build; nothing else in its bucket does. Free.
            events.Rule(
                self,
                "ExportFinished",
                event_pattern=events.EventPattern(
                    source=["aws.s3"],
                    detail_type=["Object Created"],
                    detail={
                        "bucket": {"name": [live_bucket_name]},
                        "object": {"key": [FINISHED_KEY]},
                    },
                ),
                targets=[targets.CodeBuildProject(project)],
            )

        CfnOutput(self, "SiteBucketName", value=bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        CfnOutput(self, "DistributionDomainName", value=distribution.distribution_domain_name)
        CfnOutput(self, "BuildProjectName", value=project.project_name)
        CfnOutput(self, "AlertTopicArn", value=topic.topic_arn)
