import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.platform import CommunityPost, PostComment, Space
from app.models.user import User
from app.community.schemas import (
    CommentItem,
    CreateCommentRequest,
    CreatePostRequest,
    PostAuthor,
    PostDetail,
    PostSummary,
)

router = APIRouter(prefix="/api/spaces", tags=["community"])


def _get_space_or_404(slug: str, db: Session) -> Space:
    space = db.query(Space).filter(Space.slug == slug, Space.status == "active").first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    return space


def _build_author(user: User) -> PostAuthor:
    return PostAuthor(id=user.id, name=user.name, email=user.email)


# ---------------------------------------------------------------------------
# Community feed
# ---------------------------------------------------------------------------

@router.get("/{slug}/community", response_model=list[PostSummary])
def list_community_posts(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PostSummary]:
    """Return visible community posts — pinned first, then newest."""
    space = _get_space_or_404(slug, db)

    posts = (
        db.query(CommunityPost)
        .options(joinedload(CommunityPost.author))
        .filter(
            CommunityPost.space_id == space.id,
            CommunityPost.is_visible.is_(True),
        )
        .order_by(CommunityPost.is_pinned.desc(), CommunityPost.created_at.desc())
        .all()
    )

    if not posts:
        return []

    post_ids = [p.id for p in posts]
    comment_counts: dict[str, int] = dict(
        db.query(PostComment.post_id, func.count(PostComment.id))
        .filter(
            PostComment.post_id.in_(post_ids),
            PostComment.is_visible.is_(True),
        )
        .group_by(PostComment.post_id)
        .all()
    )

    return [
        PostSummary(
            id=p.id,
            post_type=p.post_type.value if hasattr(p.post_type, "value") else str(p.post_type),
            title=p.title,
            body=p.body,
            is_pinned=p.is_pinned,
            author=_build_author(p.author),
            comment_count=comment_counts.get(p.id, 0),
            created_at=p.created_at,
        )
        for p in posts
    ]


# ---------------------------------------------------------------------------
# Single post with comments
# ---------------------------------------------------------------------------

@router.get("/{slug}/community/{post_id}", response_model=PostDetail)
def get_community_post(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostDetail:
    space = _get_space_or_404(slug, db)
    post = (
        db.query(CommunityPost)
        .options(
            joinedload(CommunityPost.author),
            joinedload(CommunityPost.comments).joinedload(PostComment.author),
        )
        .filter(
            CommunityPost.id == post_id,
            CommunityPost.space_id == space.id,
            CommunityPost.is_visible.is_(True),
        )
        .first()
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")

    visible_comments = [c for c in post.comments if c.is_visible]

    return PostDetail(
        id=post.id,
        post_type=post.post_type.value if hasattr(post.post_type, "value") else str(post.post_type),
        title=post.title,
        body=post.body,
        is_pinned=post.is_pinned,
        author=_build_author(post.author),
        comments=[
            CommentItem(
                id=c.id,
                body=c.body,
                author=_build_author(c.author),
                created_at=c.created_at,
            )
            for c in visible_comments
        ],
        created_at=post.created_at,
    )


# ---------------------------------------------------------------------------
# Create post
# ---------------------------------------------------------------------------

@router.post("/{slug}/community", response_model=PostSummary, status_code=status.HTTP_201_CREATED)
def create_community_post(
    slug: str,
    body: CreatePostRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostSummary:
    space = _get_space_or_404(slug, db)

    post = CommunityPost(
        id=str(uuid.uuid4()),
        space_id=space.id,
        author_id=current_user.id,
        post_type=body.validate_post_type(),
        title=body.title or None,
        body=body.body.strip(),
        is_pinned=False,
        is_visible=True,
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    return PostSummary(
        id=post.id,
        post_type=str(post.post_type),
        title=post.title,
        body=post.body,
        is_pinned=post.is_pinned,
        author=_build_author(current_user),
        comment_count=0,
        created_at=post.created_at,
    )


# ---------------------------------------------------------------------------
# Create comment
# ---------------------------------------------------------------------------

@router.post(
    "/{slug}/community/{post_id}/comments",
    response_model=CommentItem,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    slug: str,
    post_id: str,
    body: CreateCommentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CommentItem:
    space = _get_space_or_404(slug, db)
    post = (
        db.query(CommunityPost)
        .filter(
            CommunityPost.id == post_id,
            CommunityPost.space_id == space.id,
            CommunityPost.is_visible.is_(True),
        )
        .first()
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")

    comment = PostComment(
        id=str(uuid.uuid4()),
        post_id=post.id,
        author_id=current_user.id,
        body=body.body.strip(),
        is_visible=True,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    return CommentItem(
        id=comment.id,
        body=comment.body,
        author=_build_author(current_user),
        created_at=comment.created_at,
    )
