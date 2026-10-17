"""An untitled Conversation's opening line.

``body`` is sanitised HTML, so this is not a substring operation: tags
have to come out, entities have to be resolved before anything is
measured, and the cut has to land somewhere a reader would accept.
"""

from __future__ import annotations

import pytest

from app.community.excerpt import DEFAULT_LIMIT, plain_text_excerpt


class TestNothingToShow:
    @pytest.mark.parametrize("body", [None, "", "   ", "<p></p>", "<br><br>"])
    def test_returns_none_so_the_caller_can_fall_back(self, body):
        assert plain_text_excerpt(body) is None


class TestMarkupComesOut:
    def test_tags_are_removed_not_truncated_through(self):
        # "<p>Hello"[:4] is "<p>H", which renders as nothing at all.
        assert plain_text_excerpt("<p>Hello there</p>") == "Hello there"

    def test_inline_formatting_keeps_its_text(self):
        assert plain_text_excerpt(
            "<p>We <b>gather</b> at <em>dusk</em></p>"
        ) == "We gather at dusk"

    def test_block_boundaries_become_a_space(self):
        # Without this "one<br>two" reads as "onetwo".
        assert plain_text_excerpt("one<br>two") == "one two"
        assert plain_text_excerpt("<p>one</p><p>two</p>") == "one two"

    def test_a_link_keeps_its_label_and_loses_its_href(self):
        out = plain_text_excerpt('<p>See <a href="https://x.test">the notes</a></p>')
        assert out == "See the notes"
        assert "http" not in out

    def test_script_content_does_not_survive(self):
        # Defence in depth — the real boundary is ``sanitize``, which
        # would never have stored this. The excerpt must not reintroduce
        # it if something else does.
        out = plain_text_excerpt("<script>alert(1)</script>safe")
        assert out == "safe"


class TestEntities:
    def test_they_are_resolved_before_measuring(self):
        assert plain_text_excerpt("<p>tea &amp; toast</p>") == "tea & toast"

    def test_a_cut_cannot_land_inside_one(self):
        body = "&amp;" * 60          # 300 chars of markup, 60 of text
        out = plain_text_excerpt(body)
        assert out is not None
        assert "&amp" not in out, "the cut landed inside an entity"
        assert out == "&" * 60


class TestLength:
    def test_short_text_is_returned_whole_with_no_ellipsis(self):
        assert plain_text_excerpt("A quiet evening") == "A quiet evening"

    def test_long_text_is_cut_and_marked(self):
        out = plain_text_excerpt("word " * 60)
        assert out is not None
        assert out.endswith("…")
        assert len(out) <= DEFAULT_LIMIT + 1

    def test_the_cut_prefers_a_word_boundary(self):
        body = (
            "The quiet part of the evening is when we gather and sit "
            "together in the warm lamplight and simply breathe out"
        )
        out = plain_text_excerpt(body)
        assert out is not None
        assert out.endswith("…")
        assert "  " not in out
        # Ends on a whole word, not mid-syllable.
        assert body.startswith(out[:-1])
        assert not out[:-1].endswith(" ")

    def test_one_very_long_word_is_clipped_rather_than_dropped(self):
        out = plain_text_excerpt("a" * 300)
        assert out == "a" * DEFAULT_LIMIT + "…", (
            "a body with no spaces must still produce something"
        )

    def test_the_limit_is_configurable(self):
        assert plain_text_excerpt("one two three four", limit=7) == "one two…"


class TestWhitespace:
    def test_runs_collapse(self):
        assert plain_text_excerpt("<p>a   \n\n  b</p>") == "a b"
