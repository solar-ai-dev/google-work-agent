"""Deterministic endpoint policy registry for the local API."""

from __future__ import annotations

import re
from dataclasses import dataclass

from google_work_agent.ports import EndpointPolicy


@dataclass(frozen=True, slots=True)
class EndpointRule:
    methods: tuple[str, ...]
    template: str
    policy: EndpointPolicy
    _pattern: re.Pattern[str]

    @classmethod
    def create(
        cls,
        *,
        methods: tuple[str, ...],
        template: str,
        policy: EndpointPolicy,
    ) -> EndpointRule:
        pattern = "^" + re.sub(r"\{[^/]+\}", r"[^/]+", template) + "$"
        return cls(methods=methods, template=template, policy=policy, _pattern=re.compile(pattern))

    def matches(self, *, method: str, path: str) -> bool:
        return method.upper() in self.methods and self._pattern.match(path) is not None


@dataclass(frozen=True, slots=True)
class EndpointPolicyRegistry:
    rules: tuple[EndpointRule, ...]

    def resolve(self, *, method: str, path: str) -> EndpointPolicy | None:
        for rule in self.rules:
            if rule.matches(method=method, path=path):
                return rule.policy
        return None


DEFAULT_ENDPOINT_POLICY_REGISTRY = EndpointPolicyRegistry(
    rules=(
        EndpointRule.create(
            methods=("GET",),
            template="/health/live",
            policy=EndpointPolicy.HEALTH_PUBLIC,
        ),
        EndpointRule.create(
            methods=("GET",),
            template="/health/ready",
            policy=EndpointPolicy.HEALTH_PUBLIC,
        ),
        EndpointRule.create(
            methods=("POST",),
            template="/api/v1/session/bootstrap",
            policy=EndpointPolicy.BOOTSTRAP_EXCHANGE,
        ),
        EndpointRule.create(
            methods=("POST",),
            template="/api/v1/google/oauth/start",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("GET",),
            template="/api/v1/google/connection",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("POST",),
            template="/api/v1/google/disconnect",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("GET",),
            template="/api/v1/runtime",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("GET",),
            template="/api/v1/identity/google-account",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("POST", "GET"),
            template="/api/v1/conversations",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("GET",),
            template="/api/v1/conversations/{conversation_id}",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("GET",),
            template="/api/v1/conversations/{conversation_id}/latest-run",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("POST",),
            template="/api/v1/runs",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("GET",),
            template="/api/v1/runs/{run_id}",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("GET",),
            template="/api/v1/runs/{run_id}/context",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("POST",),
            template="/api/v1/runs/{run_id}/cancel",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("POST",),
            template="/api/v1/runs/{run_id}/resume",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("GET",),
            template="/api/v1/runs/{run_id}/events",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("POST",),
            template="/api/v1/actions/{action_id}/approve",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("POST",),
            template="/api/v1/actions/{action_id}/modify",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("POST",),
            template="/api/v1/actions/{action_id}/reject",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("POST",),
            template="/api/v1/actions/{action_id}/prepare-retry",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("GET",),
            template="/api/v1/resources/gmail",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("GET",),
            template="/api/v1/resources/tasks",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
        EndpointRule.create(
            methods=("GET",),
            template="/api/v1/resources/calendar",
            policy=EndpointPolicy.API_SESSION_REQUIRED,
        ),
    )
)
