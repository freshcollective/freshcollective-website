from datetime import datetime
from pydantic import BaseModel, computed_field

VALID_POST_TYPES = {"prompt", "reflection", "discussion", "announcement"}


class PostAuthor(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str | None
    email: str

    @computed_field
    @property
    def display_name(self) -> str:
        return self.name or self.email.split("@")[0]


class CommentItem(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    body: str
    author: PostAuthor
    created_at: datetime


class PostSummary(BaseModel):
    """Community post for the feed — includes comment count, no comment bodies."""

    id: str
    post_type: str
    title: str | None
    body: str
    is_pinned: bool
    author: PostAuthor
    comment_count: int
    created_at: datetime


class PostDetail(BaseModel):
    """Full post with all comments."""

    id: str
    post_type: str
    title: str | None
    body: str
    is_pinned: bool
    author: PostAuthor
    comments: list[CommentItem]
    created_at: datetime


class CreatePostRequest(BaseModel):
    post_type: str = "discussion"
    title: str | None = None
    body: str

    def validate_post_type(self) -> str:
        pt = self.post_type.lower()
        if pt not in VALID_POST_TYPES:
            return "discussion"
        return pt


class CreateCommentRequest(BaseModel):
    body: str
