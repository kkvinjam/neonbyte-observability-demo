#!/usr/bin/env python3
"""Render the NeonByte Kubernetes manifests (EKS Auto Mode) from environment variables.

    REGISTRY=<acct>.dkr.ecr.<region>.amazonaws.com IMAGE_TAG=v1 ... python deploy/k8s/render.py > neonbyte.yaml

Used by the stack's CodeBuild project (deploy/scripts/k8s-apply.sh). Stdlib only.

Observability, as in the reference EKS service: the amazon-cloudwatch-observability add-on
runs the CloudWatch agent + Fluent Bit, and the `instrumentation.opentelemetry.io/inject-python`
pod annotation makes its operator inject the ADOT Python auto-instrumentation (zero code)
-> Application Signals, X-Ray traces, Container Insights, and container logs in CloudWatch.
"""

from __future__ import annotations

import json
import os
import sys

NS = "neonbyte"
APPS = ["storefront", "catalog", "cart", "orders", "payments"]


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        sys.exit(f"render.py: missing required env var {name}")
    return value


def doc(obj: dict) -> str:
    # JSON is valid YAML; one document per object keeps kubectl happy and avoids a PyYAML dependency.
    return json.dumps(obj, indent=1)


def app_deployment(app: str, registry: str, tag: str, replicas: int) -> list[dict]:
    labels = {"app": app, "app.kubernetes.io/part-of": "neonbyte"}
    container_env = [
        {"name": "AWS_REGION", "value": env("AWS_REGION")},
        {"name": "PARAMETER_STORE_PREFIX", "value": "/neonbyte"},
        {"name": "PRODUCTS_TABLE", "value": env("PRODUCTS_TABLE")},
        {"name": "CARTS_TABLE", "value": env("CARTS_TABLE")},
        {"name": "ORDERS_TABLE", "value": env("ORDERS_TABLE")},
        {"name": "CATALOG_URL", "value": "http://catalog:8080"},
        {"name": "CART_URL", "value": "http://cart:8080"},
        {"name": "ORDERS_URL", "value": "http://orders:8080"},
        {"name": "PAYMENTS_URL", "value": "http://payments:8080"},
        # Merged with what the CloudWatch operator injects (service name, exporters, sampler).
        {"name": "OTEL_PYTHON_LOG_CORRELATION", "value": "true"},
        {"name": "OTEL_PYTHON_EXCLUDED_URLS", "value": "/health"},
    ]
    probe = {"httpGet": {"path": "/health", "port": 8080}, "periodSeconds": 15, "timeoutSeconds": 5}
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": app, "namespace": NS, "labels": labels},
        "spec": {
            "replicas": replicas,
            "selector": {"matchLabels": {"app": app}},
            "template": {
                "metadata": {
                    "labels": labels,
                    "annotations": {"instrumentation.opentelemetry.io/inject-python": "true"},
                },
                "spec": {
                    "serviceAccountName": "neonbyte-app",
                    "nodeSelector": {"kubernetes.io/arch": "arm64"},
                    "containers": [
                        {
                            "name": app,
                            "image": f"{registry}/neonbyte/{app}:{tag}",
                            "ports": [{"containerPort": 8080, "name": "http"}],
                            "env": container_env,
                            # httpGet probes: no python process, so ADOT never runs inside a probe.
                            "readinessProbe": {**probe, "initialDelaySeconds": 5},
                            "livenessProbe": {**probe, "initialDelaySeconds": 30, "failureThreshold": 4},
                            "resources": {"requests": {"cpu": "250m", "memory": "384Mi"}, "limits": {"memory": "768Mi"}},
                            "securityContext": {"allowPrivilegeEscalation": False, "runAsNonRoot": True, "runAsUser": 1000},
                        }
                    ],
                },
            },
        },
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": app, "namespace": NS, "labels": labels},
        "spec": {"type": "ClusterIP", "selector": {"app": app}, "ports": [{"name": "http", "port": 8080, "targetPort": 8080}]},
    }
    return [deployment, service]


def ingress_class(name: str, scheme: str) -> list[dict]:
    return [
        {
            "apiVersion": "eks.amazonaws.com/v1",
            "kind": "IngressClassParams",
            "metadata": {"name": name},
            "spec": {"scheme": scheme},
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "IngressClass",
            "metadata": {"name": name},
            "spec": {
                "controller": "eks.amazonaws.com/alb",
                "parameters": {"apiGroup": "eks.amazonaws.com", "kind": "IngressClassParams", "name": name},
            },
        },
    ]


def ingress(name: str, cls: str, security_group: str, rules: list[tuple[str, str]], extra_attrs: str = "") -> dict:
    attrs = "routing.http.drop_invalid_header_fields.enabled=true" + (f",{extra_attrs}" if extra_attrs else "")
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": name,
            "namespace": NS,
            "annotations": {
                "alb.ingress.kubernetes.io/target-type": "ip",
                "alb.ingress.kubernetes.io/healthcheck-path": "/health",
                # Stack-owned security groups; ALB -> pod rules live in the stack too.
                "alb.ingress.kubernetes.io/security-groups": security_group,
                "alb.ingress.kubernetes.io/manage-backend-security-group-rules": "false",
                "alb.ingress.kubernetes.io/load-balancer-attributes": attrs,
                # No custom `alb.ingress.kubernetes.io/tags`: EKS Auto Mode's managed
                # AmazonEKSLoadBalancingPolicy only allows its own tag keys on ELB create calls.
            },
        },
        "spec": {
            "ingressClassName": cls,
            "rules": [
                {
                    "http": {
                        "paths": [
                            {"path": path, "pathType": "Prefix", "backend": {"service": {"name": svc, "port": {"number": 8080}}}}
                            for path, svc in rules
                        ]
                    }
                }
            ],
        },
    }


def main() -> None:
    registry, tag = env("REGISTRY"), env("IMAGE_TAG")
    replicas = int(env("REPLICAS", "1"))
    objects: list[dict] = [
        # Graviton capacity for every NeonByte pod (the built-in general-purpose pool is amd64-only).
        {
            "apiVersion": "karpenter.sh/v1",
            "kind": "NodePool",
            "metadata": {"name": "neonbyte-arm64"},
            "spec": {
                "template": {
                    "spec": {
                        "nodeClassRef": {"group": "eks.amazonaws.com", "kind": "NodeClass", "name": "default"},
                        "requirements": [
                            {"key": "kubernetes.io/arch", "operator": "In", "values": ["arm64"]},
                            {"key": "karpenter.sh/capacity-type", "operator": "In", "values": ["on-demand"]},
                            {"key": "eks.amazonaws.com/instance-category", "operator": "In", "values": ["c", "m", "r"]},
                            {"key": "eks.amazonaws.com/instance-generation", "operator": "Gt", "values": ["5"]},
                        ],
                    }
                },
                "limits": {"cpu": "64"},
                "disruption": {"consolidationPolicy": "WhenEmptyOrUnderutilized", "consolidateAfter": "5m"},
            },
        },
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NS}},
        # Bound to the stack's IAM role through an EKS Pod Identity association.
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": "neonbyte-app", "namespace": NS}},
    ]
    for app in APPS:
        objects += app_deployment(app, registry, tag, replicas)

    objects += ingress_class("neonbyte-public", "internet-facing")
    objects += ingress_class("neonbyte-internal", "internal")
    # Public ALB: reachable only from CloudFront (its security group admits the origin-facing prefix list).
    objects.append(
        ingress("storefront", "neonbyte-public", env("PUBLIC_ALB_SG"), [("/", "storefront")], "idle_timeout.timeout_seconds=180")
    )
    # Internal ALB: how the AgentCore agents (VPC mode, outside the cluster) reach the backends.
    objects.append(
        ingress(
            "backends",
            "neonbyte-internal",
            env("INTERNAL_ALB_SG"),
            [("/products", "catalog"), ("/categories", "catalog"), ("/carts", "cart"), ("/orders", "orders"), ("/payments", "payments")],
        )
    )

    objects.append(
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "loadgen", "namespace": NS, "labels": {"app": "loadgen"}},
            "spec": {
                "replicas": int(env("LOADGEN_REPLICAS", "1")),
                "selector": {"matchLabels": {"app": "loadgen"}},
                "template": {
                    "metadata": {"labels": {"app": "loadgen"}},
                    "spec": {
                        "serviceAccountName": "neonbyte-app",
                        "nodeSelector": {"kubernetes.io/arch": "arm64"},
                        "containers": [
                            {
                                "name": "loadgen",
                                "image": f"{registry}/neonbyte/loadgen:{tag}",
                                "env": [
                                    # The CloudFront URL is published to SSM after the distribution exists.
                                    {"name": "TARGET_URL_PARAM", "value": "/neonbyte/storefronturl"},
                                    {"name": "AWS_REGION", "value": env("AWS_REGION")},
                                    {"name": "USERS", "value": env("LOADGEN_USERS", "5")},
                                    {"name": "CHAT_PROBABILITY", "value": env("LOADGEN_CHAT_PROBABILITY", "0.05")},
                                    {"name": "REPORT_EVERY", "value": "300"},
                                ],
                                "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "256Mi"}},
                                "securityContext": {"allowPrivilegeEscalation": False, "runAsNonRoot": True, "runAsUser": 1000},
                            }
                        ],
                    },
                },
            },
        }
    )
    print("\n---\n".join(doc(o) for o in objects))


if __name__ == "__main__":
    main()
