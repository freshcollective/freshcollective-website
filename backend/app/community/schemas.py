from datetime import datetime
from pydantic import BaseModel, Field, computed_field

# Community Phase 1 — extended type vocabulary. Existing enum values
# (`prompt`, `reflection`, `discussion`, `announcement`) stay valid so
# legacy posts keep working.
VALID_POST_TYPES = {
    "reflection",
    "question",
    "poll",
    "announcement",
    "celebration",
    "share",
    # Legacy — accepted so historical posts round-trip cleanly.
    "prompt",
    "discussion",
}

# Default when the client omits a type or sends something unknown.
DEFAULT_POST_TYPE = "reflection"

ALLOWED_REACTION_EMOJIS = {"❤️", "🙌", "🔥", "👏", "😂", "💡"}


class PostAuthor(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str | None
    email: str

    @computed_field
    @property
    def display_name(self) -> str:
        return self.name or self.email.split("@")[0]


class ReactionCount(BaseModel):
    emoji: str
    count: int
    reacted: bool  # whether the current user has reacted with this emoji


# ---------------------------------------------------------------------------
# Poll payloads
# ---------------------------------------------------------------------------

class PollOptionView(BaseModel):
    id: str
    label: str
    position: int
    vote_count: int
    voted: bool  # whether the current user has cast a vote for this option


class PollView(BaseModel):
    """Poll payload served alongside a Post. Result visibility is
    resolved server-side so the client renders exactly what it should
    see (Atlas principle: no data the interface won't show)."""

    allow_multiple: bool
    is_anonymous: bool
    show_results_before_vote: bool
    closes_at: datetime | None
    total_voters: int
    user_has_voted: bool
    can_edit: bool  # question editable while no votes exist
    is_closed: bool
    show_results: bool  # combines the three "should the current user see counts" rules
    options: list[PollOptionView]


class PollOptionInput(BaseModel):
    label: str = Field(min_length=1, max_length=300)


class PollInput(BaseModel):
    """Client-authored poll config on post creation."""

    options: list[PollOptionInput] = Field(min_length=2, max_length=20)
    allow_multiple: bool = False
    is_anonymous: bool = False
    show_results_before_vote: bool = False
    closes_at: datetime | None = None


class CastVoteRequest(BaseModel):
    # Empty list clears the user's vote(s).
    option_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

class CommentItem(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    body: str
    image_url: str | None
    author: PostAuthor
    created_at: datetime
    reactions: list[ReactionCount] = []
    # Community Phase 1
    parent_comment_id: str | None = None
    parent_author_name: str | None = None
    mentioned_user_ids: list[str] = []


class CreateCommentRequest(BaseModel):
    body: str
    image_url: str | None = None
    parent_comment_id: str | None = None
    mentioned_user_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

class PostSummary(BaseModel):
    """Community post for the feed — includes comment count, no comment bodies."""

    id: str
    post_type: str
    title: str | None
    body: str
    image_url: str | None
    is_pinned: bool
    author: PostAuthor
    comment_count: int
    created_at: datetime
    reactions: list[ReactionCount] = []
    # Community Phase 1
    mentioned_user_ids: list[str] = []
    poll: PollView | None = None
    # Community Phase 2 — scheduling. Populated for scheduled + published
    # posts alike so the creator UI can label them consistently.
    publication_status: str = "published"
    scheduled_for: datetime | None = None
    scheduling_timezone: str | None = None
    published_at: datetime | None = None


class PostDetail(BaseModel):
    """Full post with all comments."""

    id: str
    post_type: str
    title: str | None
    body: str
    image_url: str | None
    is_pinned: bool
    author: PostAuthor
    comments: list[CommentItem]
    created_at: datetime
    reactions: list[ReactionCount] = []
    # Community Phase 1
    mentioned_user_ids: list[str] = []
    poll: PollView | None = None
    # Community Phase 2 — scheduling
    publication_status: str = "published"
    scheduled_for: datetime | None = None
    scheduling_timezone: str | None = None
    published_at: datetime | None = None


class CreatePostRequest(BaseModel):
    post_type: str = DEFAULT_POST_TYPE
    title: str | None = None
    body: str
    image_url: str | None = None
    mentioned_user_ids: list[str] = Field(default_factory=list)
    poll: PollInput | None = None
    # Community Phase 2 — scheduling
    #   scheduled_for:       UTC timestamp when the post should publish.
    #                        None means publish immediately.
    #   scheduling_timezone: display-only string (e.g. "Australia/Melbourne")
    #   is_pinned:           creator-only; ordinary members ignored.
    scheduled_for: datetime | None = None
    scheduling_timezone: str | None = None
    is_pinned: bool = False
    # Channels — the destination Channel's slug (within the current Space).
    # Omitting is equivalent to posting to the Space's default Common
    # Room (channel_type='general'), which keeps existing composers
    # working during rollout.
    channel_slug: str | None = None

    def validate_post_type(self) -> str:
        pt = (self.post_type or DEFAULT_POST_TYPE).lower()
        if pt not in VALID_POST_TYPES:
            return DEFAULT_POST_TYPE
        return pt


class ScheduleUpdateRequest(BaseModel):
    """Reschedule payload for PATCH /creator/spaces/{slug}/community/{id}."""
    scheduled_for: datetime | None = None
    scheduling_timezone: str | None = None


# ---------------------------------------------------------------------------
# Member search (@ autocomplete) and community search
# ---------------------------------------------------------------------------

class MemberSuggestion(BaseModel):
    id: str
    display_name: str
    avatar_url: str | None = None
    role: str


class SearchHit(BaseModel):
    """A single search result. `kind` tells the UI what it is; `post_id`
    is always the link target so results always resolve to a discussion."""

    kind: str  # 'post' | 'comment'
    post_id: str
    post_type: str
    post_title: str | None
    author_name: str
    excerpt: str  # short snippet around the match
    created_at: datetime
    match_field: str  # 'title' | 'body' | 'comment' | 'author'


class SearchResponse(BaseModel):
    query: str
    total: int
    hits: list[SearchHit]
