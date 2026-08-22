"""Base model invariants shared by Local API wire schemas."""

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContractVersionedRequest(ApiModel):
    api_contract_version: str
