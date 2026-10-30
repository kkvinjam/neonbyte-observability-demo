"""Static checks on the CloudFormation template (skipped when cfn-lint is not installed)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "deploy/cloudformation/neonbyte.yaml"


@pytest.mark.skipif(shutil.which("cfn-lint") is None, reason="cfn-lint not installed")
def test_cfn_lint_clean():
    result = subprocess.run(["cfn-lint", "-r", "us-east-1", "us-west-2", "--", str(TEMPLATE)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_dashboard_body_is_json():
    cfnlint = pytest.importorskip("cfnlint.decode")
    tpl, _ = cfnlint.decode(str(TEMPLATE))
    body = tpl["Resources"]["Dashboard"]["Properties"]["DashboardBody"]["Fn::Sub"][0]
    assert json.loads(re.sub(r"\$\{[^}]+\}", "x", body))["widgets"]


def test_no_world_open_ingress():
    text = TEMPLATE.read_text()
    assert "CidrIp: 0.0.0.0/0" not in text  # ALB is reachable from CloudFront's prefix list only


def test_k8s_manifests_render(monkeypatch):
    import subprocess as sp
    import sys

    env = dict(
        REGISTRY="r", IMAGE_TAG="t", AWS_REGION="us-east-1", PRODUCTS_TABLE="p", CARTS_TABLE="c",
        ORDERS_TABLE="o", PUBLIC_ALB_SG="sg-1", INTERNAL_ALB_SG="sg-2",
    )
    out = sp.run([sys.executable, str(TEMPLATE.parents[1] / "k8s/render.py")], env=env, capture_output=True, text=True, check=True).stdout
    docs = [json.loads(d) for d in out.split("\n---\n")]
    kinds = [d["kind"] for d in docs]
    assert kinds.count("Deployment") == 6 and kinds.count("Ingress") == 2
    for d in docs:
        if d["kind"] == "Deployment" and d["metadata"]["name"] != "loadgen":
            assert d["spec"]["template"]["metadata"]["annotations"]["instrumentation.opentelemetry.io/inject-python"] == "true"
