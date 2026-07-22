"""Community Care — member-facing intake surface (Stage 2B).

The admin review muscle lives at ``app.admin.community_care``. Both
packages share primitives (case numbering, dedupe, snapshot, event
writer) from ``app.community_care.shared`` so the audit trail is
identical regardless of which entry point opened the case.
"""
