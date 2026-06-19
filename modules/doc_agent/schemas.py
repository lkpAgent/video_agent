from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContentItem:
    title: str
    content: str
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "source_url": self.source_url,
        }


@dataclass
class MediaAsset:
    kind: str
    title: str
    source_url: str
    local_path: str = ""
    alt: str = ""
    asset_id: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    suggested_pages: list[str] = field(default_factory=list)
    is_official: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "source_url": self.source_url,
            "local_path": self.local_path,
            "alt": self.alt,
            "asset_id": self.asset_id,
            "description": self.description,
            "tags": self.tags,
            "suggested_pages": self.suggested_pages,
            "is_official": self.is_official,
        }


@dataclass
class ContentBundle:
    source_type: str
    title: str
    summary: str
    raw_materials: list[ContentItem] = field(default_factory=list)
    key_facts: list[str] = field(default_factory=list)
    code_examples: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    media_assets: list[MediaAsset] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "title": self.title,
            "summary": self.summary,
            "raw_materials": [item.to_dict() for item in self.raw_materials],
            "key_facts": self.key_facts,
            "code_examples": self.code_examples,
            "links": self.links,
            "media_assets": [asset.to_dict() for asset in self.media_assets],
        }


@dataclass
class PageSpec:
    page_id: str
    page_type: str
    title: str
    subtitle: str = ""
    bullets: list[str] = field(default_factory=list)
    narration: str = ""
    duration: float = 8.0
    code: str = ""
    accent: str = ""
    media_path: str = ""
    media_alt: str = ""
    media_asset_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "page_type": self.page_type,
            "title": self.title,
            "subtitle": self.subtitle,
            "bullets": self.bullets,
            "narration": self.narration,
            "duration": self.duration,
            "code": self.code,
            "accent": self.accent,
            "media_path": self.media_path,
            "media_alt": self.media_alt,
            "media_asset_id": self.media_asset_id,
        }


@dataclass
class PageScript:
    title: str
    audience: str
    style: str
    pages: list[PageSpec]
    visual_style: str = "bright_unified"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "audience": self.audience,
            "style": self.style,
            "visual_style": self.visual_style,
            "pages": [page.to_dict() for page in self.pages],
        }
