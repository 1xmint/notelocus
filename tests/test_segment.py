"""What splitting a note is allowed to do to it.

Tests are named as the claim they make. The negative ones are the point: this
tool runs over notes somebody cares about, so what it must *not* do matters more
than what it does.
"""

from notelocus.segment import MIN_SEGMENT_CHARS, extract_tags, split


def test_an_empty_document_yields_nothing():
    assert split("") == []
    assert split("\n\n   \n") == []


def test_a_heading_starts_a_new_idea():
    segments = split("# One\n\nbody one\n\n# Two\n\nbody two\n")
    assert [s.title for s in segments] == ["One", "Two"]
    assert all(s.strategy == "heading" for s in segments)


def test_a_short_idea_under_its_own_heading_is_not_folded_away():
    """A heading is a boundary the author typed.

    The fragment merger exists for paragraph splitting, which over-splits. If it
    ran over headings it would silently discard structure somebody wrote by
    hand, which is the one thing this tool must never do.
    """
    document = "# Keep me\n\ntiny\n\n# Me too\n\nalso tiny\n"
    assert len(split(document)) == 2


def test_a_hash_inside_a_fenced_block_is_not_a_heading():
    document = "# Real\n\n```sh\n# not a heading, a shell comment\necho hi\n```\n\nmore text\n"
    assert [s.title for s in split(document)] == ["Real"]


def test_a_conversation_splits_on_speaker_turns_when_it_has_no_headings():
    document = (
        "You:\nwhat about the thing\n\nAssistant:\nhere is a long answer about the thing "
        "that goes on for a while\n\nYou:\nbut what about the other thing\n"
    )
    segments = split(document)
    assert len(segments) == 3
    assert all(s.strategy == "turn" for s in segments)


def test_headings_win_over_turns_when_a_document_has_both():
    """Order matters: the more structured signal is the more trustworthy one."""
    document = "# Heading\n\nYou:\nsomething\n\n# Another\n\nmore\n"
    assert all(s.strategy == "heading" for s in split(document))


def test_unstructured_prose_falls_back_to_paragraphs():
    document = "\n\n".join(f"paragraph number {i} " + "with enough words " * 12 for i in range(4))
    segments = split(document)
    assert len(segments) == 4
    assert all(s.strategy == "paragraph" for s in segments)


def test_paragraph_fragments_are_merged_rather_than_dropped():
    """A stray line is sometimes the whole point of the note.

    It gets attached to the idea before it. What it must never do is disappear.
    """
    long_paragraph = "a real idea " * 40
    document = f"{long_paragraph}\n\nshort trailing thought\n"
    segments = split(document)
    assert len(segments) == 1
    assert "short trailing thought" in segments[0].text


def test_no_content_is_lost_when_paragraphs_are_merged():
    document = "\n\n".join(["first " * 60, "tiny", "another tiny", "last " * 60])
    joined = " ".join(s.text for s in split(document))
    for fragment in ("tiny", "another tiny"):
        assert fragment in joined


def test_a_segment_records_where_it_came_from():
    segments = split("# One\n\nbody\n\n# Two\n\nbody\n")
    assert segments[0].start_line == 1
    assert segments[1].start_line == 5


def test_splitting_is_deterministic():
    document = "# A\n\n" + "words " * 50 + "\n\n# B\n\n" + "other " * 50
    first = [(s.title, s.body, s.start_line) for s in split(document)]
    second = [(s.title, s.body, s.start_line) for s in split(document)]
    assert first == second


def test_a_title_is_never_empty():
    for document in ("just some prose with no structure at all " * 5, "---\n\nafter a rule\n"):
        assert all(s.title.strip() for s in split(document))


def test_a_tag_is_a_hash_against_a_letter_and_a_heading_is_not():
    assert extract_tags("this is #tagged and #also-tagged") == ("tagged", "also-tagged")
    assert extract_tags("# Heading\n\nbody") == ()


def test_tags_are_lowercased_and_deduplicated_in_order():
    assert extract_tags("#Alpha #beta #ALPHA") == ("alpha", "beta")


def test_the_fragment_threshold_is_what_the_merger_actually_uses():
    """Guards the constant against being changed without changing behaviour."""
    short = "x" * (MIN_SEGMENT_CHARS - 50)
    long = "y" * (MIN_SEGMENT_CHARS + 50)
    assert len(split(f"{long}\n\n{short}")) == 1
    assert len(split(f"{long}\n\n{long}")) == 2
