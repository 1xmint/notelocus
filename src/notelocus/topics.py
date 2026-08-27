"""Deciding which notes belong together.

Whole-document shingle similarity is the wrong instrument here. It measures
*wording*, so two long notes about the same subject written weeks apart score
near zero. `identity.similarity` stays where it is, for finding the same text
twice.

A topic is instead built from **distinctive vocabulary**: the words that are
common inside a note and rare across the pile. That is TF-IDF, computed by hand
because it is twenty lines and a dependency here is a dependency that gets to
read somebody's private notes.

Filenames carry real signal too and are not thrown away. Someone who writes
`cortex foundation.txt` next to `CORTEX.txt` has already told you they are
related, and no amount of vocabulary analysis says it more clearly.

Everything is deterministic. The same folder produces the same grouping every
run, which is what makes it safe for a tool that moves files: filing that
reshuffles itself is worse than no filing.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

#: Words carrying no topic signal. Short rather than exhaustive: a real stopword
#: list is a dependency, and TF-IDF already suppresses anything that appears in
#: most documents. These are the ones that survive that and still say nothing.
STOPWORDS = frozenset("""
a about above after again against all am an and any are aren as at be because
been before being below between both but by can cannot could couldn did didn do
does doesn doing don down during each few for from further had hadn has hasn
have haven having he her here hers herself him himself his how i if in into is
isn it its itself just let me more most mustn my myself no nor not of off on
once only or other ought our ours ourselves out over own same shan she should
shouldn so some such than that the their theirs them themselves then there these
they this those through to too under until up very was wasn we were weren what
when where which while who whom why with won would wouldn you your yours
yourself yourselves also like get got make made use used using one two three
new thing things way ways lot really actually maybe okay yeah yes able
""".split())

#: How many distinctive terms describe a note. Enough to overlap with a related
#: note, few enough that two notes sharing three words are not called a topic.
PROFILE_TERMS = 24

#: A term must be at least this long. Two-letter tokens are almost always noise
#: once stopwords are gone.
MIN_TERM_CHARS = 3

#: Above this combined score, two notes are the same topic. Tuned against a real
#: desktop of 45 notes: lower and everything collapses into one folder, higher
#: and obviously-related files stay apart.
GROUP_THRESHOLD = 0.16

#: How much a shared filename token counts for. Filenames are a deliberate
#: statement about what a file is, so they are weighted comparably to the whole
#: vocabulary profile rather than as a tiebreak.
FILENAME_WEIGHT = 0.5

_WORD = re.compile(r"[a-z][a-z0-9'\-]*")


@dataclass(frozen=True)
class Profile:
    """What a note is about, reduced to terms."""

    key: str
    #: Distinctive terms, strongest first.
    terms: tuple[str, ...]
    #: Tokens from the filename, which are a deliberate statement about content.
    name_tokens: frozenset[str]
    weights: dict[str, float] = field(default_factory=dict)


def tokenise(text: str) -> list[str]:
    """Lowercase words worth counting."""
    return [
        word
        for word in _WORD.findall(text.lower())
        if len(word) >= MIN_TERM_CHARS and word not in STOPWORDS
    ]


def name_tokens(filename: str) -> frozenset[str]:
    """Topic tokens from a filename.

    The extension goes, and so does anything a stopword filter would drop, so
    `BID MEME COIN.txt` and `fun meme coin.txt` meet at `meme` and `coin`.
    """
    stem = filename.rsplit(".", 1)[0]
    # Split on anything that is not a letter or digit, and also at camelCase
    # boundaries, so `HEY-VERA-ORG-PLAN` and `heyveraApp` both come apart.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem)
    return frozenset(tokenise(re.sub(r"[^A-Za-z0-9]+", " ", spaced)))


def profiles(documents: dict[str, tuple[str, str]]) -> list[Profile]:
    """Build a profile per document.

    `documents` maps a key to `(filename, text)`. Returned in key order so that
    everything downstream is deterministic.
    """
    counts = {key: Counter(tokenise(text)) for key, (_, text) in documents.items()}

    # Document frequency: how many notes each term appears in at all.
    appearances: Counter[str] = Counter()
    for terms in counts.values():
        appearances.update(terms.keys())

    total = max(len(documents), 1)
    out: list[Profile] = []
    for key in sorted(documents):
        filename, _ = documents[key]
        counted = counts[key]
        longest = max(counted.values(), default=1)
        scored: dict[str, float] = {}
        for term, count in counted.items():
            # Sublinear term frequency, so one word repeated ninety times does
            # not become the whole topic - which is exactly what happens in a
            # pasted transcript that keeps saying the same product name.
            tf = 0.5 + 0.5 * (count / longest)
            idf = math.log(total / (1 + appearances[term])) + 1.0
            scored[term] = tf * idf
        top = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:PROFILE_TERMS]
        out.append(
            Profile(
                key=key,
                terms=tuple(term for term, _ in top),
                name_tokens=name_tokens(filename),
                weights=dict(top),
            )
        )
    return out


def relatedness(left: Profile, right: Profile) -> float:
    """How much two notes look like the same topic, between 0.0 and 1.0."""
    a, b = set(left.terms), set(right.terms)
    vocabulary = len(a & b) / len(a | b) if (a or b) else 0.0

    n, m = left.name_tokens, right.name_tokens
    filename = len(n & m) / len(n | m) if (n or m) else 0.0

    # A weighted mean rather than a max: both signals agreeing should beat
    # either one alone, and one strong signal should still be enough to group.
    return (vocabulary + FILENAME_WEIGHT * filename) / (1 + FILENAME_WEIGHT)


@dataclass(frozen=True)
class Topic:
    """A group of notes, and the name it earns."""

    name: str
    keys: tuple[str, ...]

    @property
    def is_singleton(self) -> bool:
        return len(self.keys) == 1


def group(
    profiles_: list[Profile],
    threshold: float = GROUP_THRESHOLD,
    anchors: dict[str, list[Profile]] | None = None,
) -> list[Topic]:
    """Group profiles into topics.

    `anchors` maps an existing topic name to the profiles already filed under it.
    A note that matches an anchor joins that topic rather than starting a new
    one, which is what stops the second run reshuffling the first run's filing.

    Grouping is by connected components: a note joins a group if it is related to
    *any* member. That chains, which for a personal pile is the behaviour you
    want - a note bridging two subjects should merge them rather than being
    forced to pick.
    """
    anchors = anchors or {}
    assigned: dict[str, str] = {}
    remaining: list[Profile] = []

    for profile in profiles_:
        best_name, best_score = None, threshold
        for name, members in sorted(anchors.items()):
            score = max((relatedness(profile, member) for member in members), default=0.0)
            if score > best_score:
                best_name, best_score = name, score
        if best_name:
            assigned[profile.key] = best_name
        else:
            remaining.append(profile)

    components = _components(remaining, threshold)

    topics: dict[str, list[str]] = {}
    for key, topic_name in assigned.items():
        topics.setdefault(topic_name, []).append(key)
    for component in components:
        members = [p for p in remaining if p.key in component]
        name = _name_for(members)
        # A new group must not collide with an existing folder unless it really
        # is that topic, which the anchor pass already decided it is not.
        while name in topics or name in anchors:
            name = f"{name}-2" if not name.endswith("-2") else f"{name}a"
        topics[name] = sorted(component)

    return [Topic(name=name, keys=tuple(sorted(keys))) for name, keys in sorted(topics.items())]


def _components(profiles_: list[Profile], threshold: float) -> list[set[str]]:
    """Connected components over the relatedness graph."""
    parent = {p.key: p.key for p in profiles_}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for i, left in enumerate(profiles_):
        for right in profiles_[i + 1 :]:
            if relatedness(left, right) >= threshold:
                a, b = find(left.key), find(right.key)
                if a != b:
                    parent[max(a, b)] = min(a, b)

    groups: dict[str, set[str]] = {}
    for profile in profiles_:
        groups.setdefault(find(profile.key), set()).add(profile.key)
    return [groups[root] for root in sorted(groups)]


def _name_for(members: list[Profile]) -> str:
    """A folder name for a group, from what its members have in common.

    Shared filename tokens win, because they are what a person already chose to
    call these things. Vocabulary is the fallback for a group that agrees on
    subject but not on naming.
    """
    if not members:
        return "unsorted"

    shared_names: Counter[str] = Counter()
    for member in members:
        shared_names.update(member.name_tokens)
    common = [term for term, n in shared_names.most_common() if n > 1 and n >= len(members) / 2]

    if not common:
        scored: Counter[str] = Counter()
        for member in members:
            for term, weight in member.weights.items():
                scored[term] += weight
        common = [term for term, _ in scored.most_common(2)]

    if not common and members[0].name_tokens:
        common = sorted(members[0].name_tokens)[:2]

    return slug("-".join(common[:2])) or "unsorted"


def slug(text: str) -> str:
    """A safe folder name.

    Windows refuses a handful of characters outright and silently drops a
    trailing dot or space, which would make a folder that cannot be addressed by
    the name it appears to have.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-.")
    return cleaned[:40].strip("-.")
