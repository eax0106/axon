"""The speech-to-text hints a call gets: the names that matter, never everyday words."""

from app.employees import keyterms


def test_the_lead_business_and_employee_come_first_then_the_scripts_names() -> None:
    terms = keyterms.build(
        lead_name="Ravi Teja",
        business="Skyline Habitats",
        employee="Ananya",
        lead_values=["Kondapur", "ravi@example.com", "98480 12345", "a long note the lead wrote"],
        script=[
            "Hello! Please greet the caller. Our 3 BHK flats are in Gachibowli",
            "near Dr. Reddy Hospital.",
            "నమస్తే, నేను స్కైలైన్ నుంచి మాట్లాడుతున్నాను.",
        ],
    )

    assert terms[:3] == ("Ravi Teja", "Skyline Habitats", "Ananya")
    assert {"Kondapur", "BHK", "Gachibowli", "Dr. Reddy Hospital"} <= set(terms)
    # Sentence-opening words, contact details and long notes are not names.
    assert not {"Hello", "Please", "Our", "ravi@example.com", "98480 12345"} & set(terms)
    assert "a long note the lead wrote" not in terms


def test_names_written_in_telugu_or_hindi_are_kept_as_written() -> None:
    terms = keyterms.build(lead_name="రవి తేజ", business="स्काईलाइन", employee="Ananya")
    assert terms == ("రవి తేజ", "स्काईलाइन", "Ananya")


def test_at_most_50_hints_each_of_64_characters_without_repeats() -> None:
    names = [f"Place{chr(65 + i // 26)}{chr(65 + i % 26)} Nagar" for i in range(80)]
    terms = keyterms.build(
        lead_name="ANANYA",
        business="Skyline",
        employee="Ananya",  # the same name again: once
        script=[", ".join(names), "Visit " + "Long" * 20 + " Street."],
    )

    assert len(terms) == keyterms.MAX_TERMS
    assert terms.count("ANANYA") == 1 and "Ananya" not in terms
    assert all(len(term) <= keyterms.MAX_CHARS for term in terms)


def test_an_employee_without_a_lead_still_gets_its_own_names() -> None:
    assert keyterms.build(lead_name=None, business="Sunrise Clinic", employee="Priya") == (
        "Sunrise Clinic",
        "Priya",
    )
