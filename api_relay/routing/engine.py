"""Route matching engine — match incoming requests to upstream providers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from api_relay.config import GatewayConfig, RouteRule
from api_relay.models import RouteMatch


class RouterEngine:
    """Matches incoming requests to upstream routes based on configured rules."""

    def __init__(self, config: GatewayConfig) -> None:
        self.routes: List[RouteRule] = config.routes

    def match(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        body: Optional[Dict[str, Any]] = None,
    ) -> Optional[RouteMatch]:
        """Find the first matching route for the request."""
        for rule in self.routes:
            match = self._evaluate_rule(rule, method, path, headers, body)
            if match:
                return match
        return None

    def _evaluate_rule(
        self,
        rule: RouteRule,
        method: str,
        path: str,
        headers: Dict[str, str],
        body: Optional[Dict[str, Any]],
    ) -> Optional[RouteMatch]:
        if rule.match_type == "path_prefix":
            return self._match_path_prefix(rule, path)
        elif rule.match_type == "header":
            return self._match_header(rule, headers, path)
        elif rule.match_type == "body_jsonpath":
            return self._match_body(rule, body, path)
        return None

    def _match_path_prefix(self, rule: RouteRule, path: str) -> Optional[RouteMatch]:
        if path.startswith(rule.match_value):
            upstream_path = path
            if rule.strip_prefix:
                upstream_path = path[len(rule.match_value) :] or "/"
            return RouteMatch(
                upstream_url=rule.target_url.rstrip("/") + upstream_path,
                extra_headers=dict(rule.target_headers),
                timeout=rule.timeout_seconds,
            )
        return None

    def _match_header(self, rule: RouteRule, headers: Dict[str, str], path: str) -> Optional[RouteMatch]:
        # match_value format: "Header-Name: value" or just "Header-Name"
        if ":" in rule.match_value:
            header_name, header_value = rule.match_value.split(":", 1)
            header_name = header_name.strip().lower()
            header_value = header_value.strip()
            actual = headers.get(header_name, "")
            if header_value in actual:
                return self._build_match(rule, path)
        else:
            header_name = rule.match_value.strip().lower()
            if header_name in headers:
                return self._build_match(rule, path)
        return None

    def _match_body(
        self,
        rule: RouteRule,
        body: Optional[Dict[str, Any]],
        path: str,
    ) -> Optional[RouteMatch]:
        if body is None:
            return None
        # match_value format: "$.field=value" or "$.field=glob_pattern"
        if "=" not in rule.match_value:
            return None

        jsonpath, expected = rule.match_value.split("=", 1)
        jsonpath = jsonpath.strip()
        expected = expected.strip()

        # Simple dotted path traversal (e.g., "$.model")
        parts = jsonpath.lstrip("$.").split(".")
        value: Any = body
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None

        if value is None:
            return None

        # Check for glob (*) match
        if expected.endswith("*"):
            if str(value).startswith(expected[:-1]):
                return self._build_match(rule, path)
        elif str(value) == expected:
            return self._build_match(rule, path)

        return None

    def _build_match(self, rule: RouteRule, path: str) -> RouteMatch:
        upstream_path = path
        if rule.strip_prefix and path.startswith(rule.match_value):
            upstream_path = path[len(rule.match_value) :] or "/"
        return RouteMatch(
            upstream_url=rule.target_url.rstrip("/") + upstream_path,
            extra_headers=dict(rule.target_headers),
            timeout=rule.timeout_seconds,
        )
