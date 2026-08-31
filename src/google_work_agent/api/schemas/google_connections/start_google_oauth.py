"""Canonical Google OAuth start wire contracts."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class StartAuthorizationRequestV1(ApiModel):
    schema_version: Literal[1]
    command_id: str


class AuthorizationStartV1(ApiModel):
    schema_version: Literal[1]
    authorization_url: str
    callback_id: str


__all__ = ["AuthorizationStartV1", "StartAuthorizationRequestV1"]
