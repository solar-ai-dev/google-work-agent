"""Stable external resource transport contracts."""

from .count_resources import ResourceCountResponse
from .get_gmail_resource import GmailAttachmentMetadataResponse, GmailResourceDetailResponse
from .list_resources import ResourceListResponse

__all__ = [
    "GmailAttachmentMetadataResponse",
    "GmailResourceDetailResponse",
    "ResourceCountResponse",
    "ResourceListResponse",
]
