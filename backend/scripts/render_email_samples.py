"""
Render every Fresh Collective email template to disk so an operator
can open the HTML files in a browser and eyeball the layout before a
launch.

Usage (from repo root):

    cd backend
    .venv/bin/python3 scripts/render_email_samples.py

Outputs:

    backend/.qa-emails/
        password_reset.html
        invitation.html
        booking_confirmation.html
        creator_announcement.html
        new_pathway.html
        reply_notification.html
        _index.html          — a small index that links to each sample

The directory is gitignored (safe to delete + regenerate). Nothing
here touches the network — Resend is not called.
"""

from __future__ import annotations

from pathlib import Path

# Ensure the app package is importable regardless of invocation cwd.
import sys
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.email_templates import (
    booking_confirmation_email,
    creator_announcement_email,
    invitation_email,
    new_pathway_email,
    password_reset_email,
    reply_notification_email,
)


SAMPLES: list[tuple[str, tuple[str, str], str]] = [
    (
        "password_reset.html",
        password_reset_email(
            reset_url="https://freshcollective.au/reset-password?token=REDACTED_SAMPLE_TOKEN",
        ),
        "Password reset — one-off, transactional.",
    ),
    (
        "invitation.html",
        invitation_email(
            inviter_name="Lindsey Hilliard",
            collective_name="The Grove",
            accept_url="https://freshcollective.au/invites/SAMPLE_TOKEN",
        ),
        "Invitation — creator → prospective member.",
    ),
    (
        "booking_confirmation.html",
        booking_confirmation_email(
            member_name="Sarah",
            gathering_title="Thursday EMBODY Circle",
            starts_when="Thursday 6 August 2026 at 7:00 PM",
            location_line="Zoom link — shared before the gathering",
            view_url="https://freshcollective.au/spaces/embody/events/SAMPLE_ID",
            add_to_calendar_url=None,
        ),
        "Booking confirmation — member-facing after booking a gathering.",
    ),
    (
        "creator_announcement.html",
        creator_announcement_email(
            creator_name="Lindsey Hilliard",
            collective_name="The Grove",
            title="A note before Sunday's circle",
            message=(
                "Before we gather on Sunday, take a quiet ten minutes with "
                "the invitation from Week 5. Let it settle. We'll open the "
                "circle with whatever surfaces."
            ),
            url="https://freshcollective.au/spaces/the-natural-leader-hub",
        ),
        "Creator announcement — broadcast from the creator's voice.",
    ),
    (
        "new_pathway.html",
        new_pathway_email(
            pathway_title="Life in Alignment — Week 5",
            collective_name="The Grove",
            pathway_url="https://freshcollective.au/spaces/the-natural-leader-hub/pathways/life-in-alignment",
            lead_line=None,
        ),
        "New pathway — fan-out to members when a new pathway is published.",
    ),
    (
        "reply_notification.html",
        reply_notification_email(
            replier_name="Emma",
            quote=(
                "This lands so clearly for me — I've been circling this "
                "same question for weeks."
            ),
            reply_url="https://freshcollective.au/spaces/the-natural-leader-hub/community/POST_ID",
            in_context="in your reflection",
        ),
        "Reply notification — someone replied to something you shared.",
    ),
]


def _index_html(entries: list[tuple[str, str, str]]) -> str:
    rows = "\n".join(
        f'  <li><a href="{fname}">{fname}</a> — <em>{subject}</em><br>'
        f'<span style="color:#64748b">{note}</span></li>'
        for fname, subject, note in entries
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>FC email samples</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif;
          max-width: 760px; margin: 40px auto; padding: 0 24px; color: #0C1826; }}
  h1 {{ font-family: Georgia, serif; font-weight: 400; }}
  ul {{ padding-left: 20px; }}
  li {{ margin: 12px 0; line-height: 1.5; }}
  em {{ color: #334155; }}
</style></head>
<body>
  <h1>Fresh Collective — email samples</h1>
  <p>These HTML files are rendered locally by
     <code>scripts/render_email_samples.py</code>. Open each to see
     the branding, layout, and copy that Resend will deliver.
     No email was sent to generate them.</p>
  <ul>
    {rows}
  </ul>
</body></html>"""


def main() -> None:
    out_dir = BACKEND_ROOT / ".qa-emails"
    out_dir.mkdir(exist_ok=True)

    entries: list[tuple[str, str, str]] = []
    for filename, (subject, html), note in SAMPLES:
        path = out_dir / filename
        path.write_text(html, encoding="utf-8")
        entries.append((filename, subject, note))
        print(f"wrote {path.relative_to(BACKEND_ROOT)}   subject: {subject!r}")

    index_path = out_dir / "_index.html"
    index_path.write_text(_index_html(entries), encoding="utf-8")
    print(f"wrote {index_path.relative_to(BACKEND_ROOT)}")
    print()
    print("Open the index in a browser:")
    print(f"  file://{index_path}")


if __name__ == "__main__":
    main()
