"""The site's stacks (S5 spec §18.2): zone and certificate in us-east-1, the site in eu-west-2.

Skipped, with a stated reason, when `node` is not on PATH (aws-cdk-lib needs it), as
tests/test_infra_stack.py is.
"""

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

if shutil.which("node") is None:
    pytest.skip("aws-cdk-lib needs Node.js (via jsii); none found on PATH", allow_module_level=True)

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

_INFRA = Path(__file__).resolve().parents[1] / "infra"
sys.path.insert(0, str(_INFRA))
from site_stacks import (  # noqa: E402
    EXPORT_PREFIX,
    FINISHED_KEY,
    SITE_DOMAIN,
    NtsbSiteDnsStack,
    NtsbSiteEdgeStack,
    NtsbSiteStack,
)

_ACCOUNT = "123456789012"
_LIVE_BUCKET = "test-live-bucket"


def _templates(
    *, live_bucket_name: str | None, alert_email: str | None = "alerts@example.invalid"
) -> dict[str, Template]:
    app = cdk.App()
    edge_env = cdk.Environment(account=_ACCOUNT, region="us-east-1")
    dns = NtsbSiteDnsStack(app, "Dns", env=edge_env)
    edge = NtsbSiteEdgeStack(app, "Edge", env=edge_env, zone=dns.zone)
    site = NtsbSiteStack(
        app,
        "Site",
        env=cdk.Environment(account=_ACCOUNT, region="eu-west-2"),
        zone=dns.zone,
        certificate=edge.certificate,
        web_acl_arn=edge.web_acl.attr_arn,
        source_branch="s5-public-site",
        alert_email=alert_email,
        live_bucket_name=live_bucket_name,
    )
    return {
        "dns": Template.from_stack(dns),
        "edge": Template.from_stack(edge),
        "site": Template.from_stack(site),
    }


@pytest.fixture(scope="module")
def stacks() -> dict[str, Template]:
    return _templates(live_bucket_name=_LIVE_BUCKET)


@pytest.fixture(scope="module")
def stacks_without_export() -> dict[str, Template]:
    return _templates(live_bucket_name=None)


@pytest.fixture(scope="module")
def stacks_without_email() -> dict[str, Template]:
    return _templates(live_bucket_name=_LIVE_BUCKET, alert_email=None)


def _statements(tpl: Template) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for resource in tpl.find_resources("AWS::IAM::Policy").values():
        found.extend(resource["Properties"]["PolicyDocument"]["Statement"])
    return found


def _as_text(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def test_zone_is_demo_floyda_dev(stacks: dict[str, Template]) -> None:
    stacks["dns"].has_resource_properties("AWS::Route53::HostedZone", {"Name": "demo.floyda.dev."})


def test_certificate_is_exact_name_and_dns_validated(stacks: dict[str, Template]) -> None:
    stacks["edge"].has_resource_properties(
        "AWS::CertificateManager::Certificate",
        {
            "DomainName": SITE_DOMAIN,
            "ValidationMethod": "DNS",
            "SubjectAlternativeNames": Match.absent(),
        },
    )


def test_site_bucket_is_private_and_versioned(stacks: dict[str, Template]) -> None:
    stacks["site"].has_resource_properties(
        "AWS::S3::Bucket",
        {
            "VersioningConfiguration": {"Status": "Enabled"},
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
        },
    )


def test_distribution_serves_the_site_name_over_https_only(stacks: dict[str, Template]) -> None:
    stacks["site"].has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "Aliases": [SITE_DOMAIN],
                    "DefaultCacheBehavior": Match.object_like(
                        {"ViewerProtocolPolicy": "redirect-to-https"}
                    ),
                }
            )
        },
    )


def test_missing_page_gets_the_404_page_with_status_404(stacks: dict[str, Template]) -> None:
    # Review Focus 2: S3 behind origin access control answers a missing key with 403.
    stacks["site"].has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "CustomErrorResponses": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "ErrorCode": 403,
                                    "ResponseCode": 404,
                                    "ResponsePagePath": "/404.html",
                                }
                            )
                        ]
                    )
                }
            )
        },
    )


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("/", "/index.html"),
        ("/methods", "/methods/index.html"),
        ("/methods/", "/methods/index.html"),
        ("/case/ABC26LA001/trail/", "/case/ABC26LA001/trail/index.html"),
        ("/_astro/site.css", "/_astro/site.css"),
        ("/404.html", "/404.html"),
    ],
)
def test_url_rewrite_maps_a_folder_address_to_its_index(uri: str, expected: str) -> None:
    # Review Focus 1. Runs the CloudFront function's own source in Node.
    source = (_INFRA / "site_url_rewrite.js").read_text()
    program = (
        f"{source}\nconst out = handler({{request: {{uri: {json.dumps(uri)}}}}});"
        "\nprocess.stdout.write(out.uri);"
    )
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(  # noqa: S603 -- fixed program, test input only
        [node, "-e", program], capture_output=True, text=True, check=True
    )
    assert result.stdout == expected


def test_alias_records_point_the_site_name_at_the_distribution(stacks: dict[str, Template]) -> None:
    for record_type in ("A", "AAAA"):
        stacks["site"].has_resource_properties(
            "AWS::Route53::RecordSet",
            {"Name": f"{SITE_DOMAIN}.", "Type": record_type, "AliasTarget": Match.any_value()},
        )


def test_build_runs_publish_in_holding_mode_from_the_given_branch(
    stacks: dict[str, Template],
) -> None:
    project = next(iter(stacks["site"].find_resources("AWS::CodeBuild::Project").values()))
    props = project["Properties"]
    assert props["SourceVersion"] == "s5-public-site"
    assert props["TimeoutInMinutes"] == 15
    assert props["Environment"]["ComputeType"] == "BUILD_GENERAL1_SMALL"
    variables = {v["Name"]: v["Value"] for v in props["Environment"]["EnvironmentVariables"]}
    assert variables["SITE_MODE"] == "holding"
    assert "bash site/scripts/publish.sh" in props["Source"]["BuildSpec"]


def test_merge_to_the_branch_starts_a_build(stacks: dict[str, Template]) -> None:
    project = next(iter(stacks["site"].find_resources("AWS::CodeBuild::Project").values()))
    triggers = project["Properties"]["Triggers"]
    assert triggers["Webhook"] is True
    (group,) = triggers["FilterGroups"]
    pairs = {(f["Type"], f["Pattern"]) for f in group}
    assert ("EVENT", "PUSH") in pairs
    (head,) = [pattern for kind, pattern in pairs if kind == "HEAD_REF"]
    # Exactly this branch: not one whose name merely contains it.
    assert re.fullmatch(head, "refs/heads/s5-public-site")
    assert not re.search(head, "refs/heads/s5-public-site-old")
    assert not re.search(head, "refs/heads/old-s5-public-site")


def test_only_the_finished_mark_starts_a_build(stacks: dict[str, Template]) -> None:
    # Review Focus 4.
    rules = stacks["site"].find_resources("AWS::Events::Rule")
    patterns = [r["Properties"].get("EventPattern") for r in rules.values()]
    s3_patterns = [p for p in patterns if p and p.get("source") == ["aws.s3"]]
    assert s3_patterns == [
        {
            "source": ["aws.s3"],
            "detail-type": ["Object Created"],
            "detail": {"bucket": {"name": [_LIVE_BUCKET]}, "object": {"key": [FINISHED_KEY]}},
        }
    ]


def test_build_role_reads_the_export_prefix_and_nothing_else_in_s4s_bucket(
    stacks: dict[str, Template],
) -> None:
    # Review Focus 5.
    live = [s for s in _statements(stacks["site"]) if _LIVE_BUCKET in _as_text(s["Resource"])]
    actions = sorted(
        a for s in live for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])
    )
    assert actions == ["s3:GetObject", "s3:ListBucket"]
    for statement in live:
        text = _as_text(statement)
        if statement["Action"] == "s3:GetObject":
            assert f"{_LIVE_BUCKET}/{EXPORT_PREFIX}*" in text
        else:
            assert _as_text(statement["Condition"]) == _as_text(
                {"StringLike": {"s3:prefix": [f"{EXPORT_PREFIX}*"]}}
            )
    for forbidden in ("runs/", "scores/", "nights/"):
        assert forbidden not in _as_text(live)


def test_without_s4s_bucket_there_is_no_export_rule_and_no_export_access(
    stacks_without_export: dict[str, Template],
) -> None:
    tpl = stacks_without_export["site"]
    patterns = [
        r["Properties"].get("EventPattern")
        for r in tpl.find_resources("AWS::Events::Rule").values()
    ]
    assert not [p for p in patterns if p and p.get("source") == ["aws.s3"]]
    assert EXPORT_PREFIX not in _as_text(_statements(tpl))


def test_failed_build_emails_the_alert_topic(stacks: dict[str, Template]) -> None:
    tpl = stacks["site"]
    tpl.has_resource_properties(
        "AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": "alerts@example.invalid"}
    )
    rules = tpl.find_resources("AWS::Events::Rule")
    failed = [
        r for r in rules.values() if "FAILED" in _as_text(r["Properties"].get("EventPattern", {}))
    ]
    assert len(failed) == 1
    assert "Ref" in _as_text(failed[0]["Properties"]["Targets"])


def test_edge_has_a_cloudfront_scope_web_acl_that_allows_by_default(
    stacks: dict[str, Template],
) -> None:
    # The flat-rate plan requires a WAF web ACL on the distribution (CloudFront developer guide,
    # "Unsupported features", read 2026-10-12).
    stacks["edge"].has_resource_properties(
        "AWS::WAFv2::WebACL", {"Scope": "CLOUDFRONT", "DefaultAction": {"Allow": {}}}
    )


def test_web_acl_has_a_per_address_rate_limit(stacks: dict[str, Template]) -> None:
    acl = next(iter(stacks["edge"].find_resources("AWS::WAFv2::WebACL").values()))
    rules = acl["Properties"]["Rules"]
    assert len(rules) <= 5  # the Free plan's rule allowance
    assert any("RateBasedStatement" in r["Statement"] for r in rules)


def test_distribution_carries_the_web_acl(stacks: dict[str, Template]) -> None:
    stacks["site"].has_resource_properties(
        "AWS::CloudFront::Distribution",
        {"DistributionConfig": Match.object_like({"WebACLId": Match.any_value()})},
    )


def test_distribution_is_on_the_flat_rate_free_plan(stacks: dict[str, Template]) -> None:
    subs = stacks["site"].find_resources("AWS::PricingPlanManager::Subscription")
    assert len(subs) == 1
    props = next(iter(subs.values()))["Properties"]
    assert props["PlanFamily"] == "CloudFront"
    assert props["PlanTier"] == "FREE"
    text = _as_text(props["ResourceArns"])
    assert "distribution/" in text
    assert "hostedzone/" in text
    assert len(props["ResourceArns"]) == 3


def test_both_holding_pages_share_one_style_block() -> None:
    # The Content-Security-Policy allows one inline style by its hash; both pages must match it.
    holding = Path(__file__).resolve().parents[1] / "site/holding"
    styles = {
        name: re.search(r"<style>(.*?)</style>", (holding / name).read_text(), re.DOTALL)
        for name in ("index.html", "404.html")
    }
    assert all(m is not None for m in styles.values())
    assert len({m.group(1) for m in styles.values() if m is not None}) == 1


def test_responses_carry_security_headers_and_a_self_only_policy(
    stacks: dict[str, Template],
) -> None:
    policies = stacks["site"].find_resources("AWS::CloudFront::ResponseHeadersPolicy")
    text = _as_text(policies)
    assert "default-src 'self'" in text
    assert "'unsafe-inline'" not in text
    assert "StrictTransportSecurity" in text


def _app_stacks(context: dict[str, str]) -> dict[str, Mapping[str, Any]]:
    import app as cdk_app  # noqa: PLC0415 -- infra/ is on sys.path only after the insert above

    app = cdk.App(context=context)
    cdk_app.add_site_stacks(app)
    return {
        stack.stack_name: Template.from_stack(stack).to_json()
        for stack in app.node.children
        if isinstance(stack, cdk.Stack)
    }


def test_every_stack_has_one_shape_whatever_context_is_given() -> None:
    # Review finding (2026-10-12): the us-east-1 stacks gained or lost their cross-region
    # export writers depending on `alert_email`, so a deploy without it would tear down what
    # the site stack reads.
    bare = _app_stacks({})
    full = _app_stacks({"alert_email": "alerts@example.invalid"})
    assert set(bare) == set(full) == {"NtsbSiteDnsStack", "NtsbSiteEdgeStack", "NtsbSiteStack"}
    assert bare["NtsbSiteDnsStack"] == full["NtsbSiteDnsStack"]
    assert bare["NtsbSiteEdgeStack"] == full["NtsbSiteEdgeStack"]


def test_without_an_email_there_is_no_subscription(
    stacks_without_email: dict[str, Template],
) -> None:
    stacks_without_email["site"].resource_count_is("AWS::SNS::Subscription", 0)


def test_build_does_not_write_statuses_to_github(stacks: dict[str, Template]) -> None:
    # Review finding (2026-10-12): CodeBuild reports build status to GitHub by default, a write.
    project = next(iter(stacks["site"].find_resources("AWS::CodeBuild::Project").values()))
    assert project["Properties"]["Source"]["ReportBuildStatus"] is False


def test_build_role_cannot_erase_the_site_buckets_history(stacks: dict[str, Template]) -> None:
    # Review finding (2026-10-12): any push to the branch runs with this role, so it must not
    # delete old versions (the way back) or set retention and legal holds.
    on_site = [s for s in _statements(stacks["site"]) if "SiteBucket" in _as_text(s["Resource"])]
    actions = {
        a for s in on_site for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])
    }
    assert actions == {"s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"}
