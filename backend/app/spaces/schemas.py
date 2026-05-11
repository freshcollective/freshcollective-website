from datetime import datetime
from pydantic import BaseModel


class PathwaySummary(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    slug: str
    title: str
    description: str | None
    status: str
    position: int


class SpaceResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    tagline: str | None
    description: str | None
    is_public: bool
    status: str
    pathways: list[PathwaySummary] = []


class SpaceSummary(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    tagline: str | None
    status: str
