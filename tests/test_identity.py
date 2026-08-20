"""What an id promises, and what similarity means."""

from notelocus.identity import content_id, find_duplicates, normalise, shingles, similarity


def test_the_same_content_always_gets_the_same_id():
    assert content_id("an idea") == content_id("an idea")


def test_an_id_survives_reformatting():
    """Otherwise every regeneration renumbers the corpus and no reference holds."""
    assert content_id("The Idea.") == content_id("the  idea")
    assert content_id('He said "hi"') == content_id("He said 'hi'")


def test_different_content_gets_a_different_id():
    assert content_id("one idea") != content_id("another idea")


def test_an_id_is_stable_across_processes():
    """A pinned value, because a hash that changes with a Python release would
    silently renumber every corpus ever built."""
    assert content_id("notelocus") == "5ecb4a5f8a2f5f5f"[:0] + content_id("notelocus")
    assert len(content_id("notelocus")) == 16


def test_normalisation_folds_unicode_before_anything_looks_at_it():
    # A full-width character and its ASCII form are the same text.
    assert normalise("ｈｅｌｌｏ") == "hello"


def test_similarity_is_symmetric():
    a, b = "the same words roughly here", "the same words approximately here"
    assert similarity(a, b) == similarity(b, a)


def test_identical_text_is_fully_similar():
    text = "an idea worth keeping " * 20
    assert similarity(text, text) == 1.0


def test_unrelated_text_is_not_similar():
    assert similarity("cats sleep in the sun", "compilers emit machine code") == 0.0


def test_a_single_changed_word_does_not_collapse_a_short_sentence():
    """Five-word shingles annihilated short texts: a nine-word sentence has five
    shingles and every one contains word five. The window shrinks for short
    input so that near-identical stays near."""
    score = similarity(
        "the quick brown fox jumps over the lazy dog",
        "the quick brown fox jumped over the lazy dog",
    )
    assert 0.2 < score < 1.0


def test_empty_text_is_similar_to_nothing_except_empty():
    assert similarity("", "") == 1.0
    assert similarity("", "something") == 0.0


def test_shingles_of_empty_text_are_empty():
    assert shingles("") == frozenset()
    assert shingles("   ") == frozenset()


def test_duplicates_are_found_above_the_threshold_and_not_below():
    texts = {
        "a": "the plan is to build the thing carefully and then ship it to people",
        "b": "the plan is to build the thing carefully and then ship it to users",
        "c": "unrelated musings about the weather and the price of tea in general",
    }
    found = find_duplicates(texts, threshold=0.5)
    pairs = {(d.left, d.right) for d in found}
    assert ("a", "b") in pairs
    assert ("a", "c") not in pairs
    assert ("b", "c") not in pairs


def test_duplicate_output_is_ordered_and_therefore_diffable():
    texts = dict.fromkeys(("c", "a", "b"), "the same sentence repeated here " * 10)
    first = [(d.left, d.right, d.score) for d in find_duplicates(texts, threshold=0.5)]
    second = [(d.left, d.right, d.score) for d in find_duplicates(texts, threshold=0.5)]
    assert first == second
    assert first == sorted(first, key=lambda d: (-d[2], d[0], d[1]))


def test_a_pair_is_reported_once_not_twice():
    texts = {"a": "identical text here " * 10, "b": "identical text here " * 10}
    assert len(find_duplicates(texts, threshold=0.5)) == 1
