import itertools
import re

from app.training.chunks import MAX_CHARS, OVERLAP_CHARS, chunk


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text)


def test_sentences_end_a_passage_at_full_stops_questions_and_the_danda() -> None:
    assert chunk("Open at nine. Closed Sunday! Parking free?") == [
        "Open at nine. Closed Sunday! Parking free?"
    ]
    hindi = "हम नौ बजे खुलते हैं। रविवार को बंद रहते हैं। पार्किंग मुफ़्त है॥ "
    sentences = [s.strip() for s in re.split(r"(?<=[।॥])\s*", hindi) if s.strip()]
    long = " ".join(f"{s} " * 20 for s in sentences)
    cut = chunk(long)
    assert len(cut) > 1 and all(c.endswith(("।", "॥")) for c in cut)  # never mid-sentence
    telugu = "మేము తొమ్మిది గంటలకు తెరుస్తాము. ఆదివారం మూసివేస్తాము."
    assert chunk(telugu) == [telugu]


def test_every_passage_is_within_the_bound_and_none_is_empty() -> None:
    text = " ".join(
        f"Sentence number {n} says something useful about plan {n}." for n in range(200)
    )
    passages = chunk(text)
    assert len(passages) > 5
    assert all(p and len(p) <= MAX_CHARS for p in passages)


def test_neighbours_overlap_and_nothing_is_lost() -> None:
    sentences = [f"Item {n} costs {n * 10} rupees today." for n in range(120)]
    passages = chunk(" ".join(sentences))
    for before, after in itertools.pairwise(passages):
        assert before.split(". ")[-1].rstrip(".") in after  # the last sentence is repeated
        assert len(before.split(". ")[-1]) <= OVERLAP_CHARS
    heard = {s for p in passages for s in re.findall(r"Item \d+ costs \d+ rupees today\.", p)}
    assert heard == set(sentences)


def test_text_with_no_break_is_still_cut() -> None:
    spaced = " ".join(["word"] * 1000)
    assert all(len(p) <= MAX_CHARS for p in chunk(spaced))
    assert words(" ".join(chunk(spaced))) == ["word"] * 1000
    solid = "x" * (MAX_CHARS * 2 + 50)  # no space, no stop
    cut = chunk(solid)
    assert [len(c) for c in cut] == [MAX_CHARS, MAX_CHARS, 50] and "".join(cut) == solid


def test_lines_are_units_and_blank_text_gives_nothing() -> None:
    menu = "Tea 20\nCoffee 30\n\nSamosa 15"
    assert chunk(menu) == ["Tea 20 Coffee 30 Samosa 15"]
    assert chunk("") == [] and chunk(" \n\t ") == []
