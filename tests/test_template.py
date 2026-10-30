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
