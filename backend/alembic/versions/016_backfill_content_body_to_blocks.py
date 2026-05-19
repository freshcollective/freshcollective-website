"""Backfill legacy content_body into pathway_step_blocks as editable text blocks.

For each pathway step where content_body is non-empty and no blocks exist,
creates one text block containing the content converted to TipTap JSON.

Revision ID: 016
Revises: 015
Create Date: 2026-05-19
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from uuid import uuid4

from alembic import op
from sqlalchemy import text

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Markdown → TipTap JSON conversion
# ---------------------------------------------------------------------------

def _parse_inline_bold(raw: str) -> list[dict]:
    """Split a text string on **bold** markers into TipTap inline nodes."""
    nodes: list[dict] = []
    parts = re.split(r"\*\*(.+?)\*\*", raw)
    for i, part in enumerate(parts):
        if not part:
            continue
        if i % 2 == 0:
            nodes.append({"type": "text", "text": part})
        else:
            nodes.append({"type": "text", "marks": [{"type": "bold"}], "text": part})
    return nodes or [{"type": "text", "text": ""}]


def _content_body_to_tiptap(content_body: str) -> str:
    """Convert legacy content_body markdown to a TipTap JSON doc string."""
    chunks = [c.strip() for c in re.split(r"\n\n+", content_body.strip()) if c.strip()]
    nodes: list[dict] = []

    for chunk in chunks:
        # Divider
        if chunk == "---":
            nodes.append({"type": "horizontalRule"})
            continue

        lines = chunk.split("\n")

        # Bullet list: every line starts with "- "
        if all(ln.startswith("- ") for ln in lines):
            items = [
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": _parse_inline_bold(ln[2:]),
                        }
                    ],
                }
                for ln in lines
            ]
            nodes.append({"type": "bulletList", "content": items})
            continue

        # Heading: single line that is entirely **text**
        if len(lines) == 1 and re.match(r"^\*\*[^*]+\*\*$", chunk):
            nodes.append(
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": chunk[2:-2]}],
                }
            )
            continue

        # Regular paragraph — join single-newline breaks with a space
        para_text = " ".join(ln.strip() for ln in lines if ln.strip())
        inline = _parse_inline_bold(para_text)
        nodes.append({"type": "paragraph", "content": inline})

    if not nodes:
        nodes = [{"type": "paragraph", "content": [{"type": "text", "text": ""}]}]

    return json.dumps({"type": "doc", "content": nodes}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.utcnow()

    rows = bind.execute(
        text(
            """
            SELECT ps.id, ps.content_body
            FROM pathway_steps ps
            WHERE ps.content_body IS NOT NULL
              AND ps.content_body != ''
              AND NOT EXISTS (
                  SELECT 1 FROM pathway_step_blocks psb
                  WHERE psb.step_id = ps.id
              )
            """
        )
    ).fetchall()

    converted = 0
    for step_id, content_body in rows:
        tiptap_json = _content_body_to_tiptap(content_body)
        block_id = str(uuid4())
        bind.execute(
            text(
                """
                INSERT INTO pathway_step_blocks
                    (id, step_id, block_type, position, content, created_at, updated_at)
                VALUES
                    (:id, :step_id, 'text', 0, :content, :now, :now)
                """
            ),
            {
                "id": block_id,
                "step_id": step_id,
                "content": tiptap_json,
                "now": now,
            },
        )
        converted += 1

    print(f"  → Converted {converted} legacy step(s) from content_body to text blocks.")


def downgrade() -> None:
    # Intentionally irreversible. Deleting the converted blocks could lose
    # content if the original content_body has since been edited.
    pass
