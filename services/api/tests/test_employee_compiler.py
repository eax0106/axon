import pytest

from app.employees.compiler import NOT_PROVIDED, STRICTNESS, compile_prompt, render
from app.employees.script import CaptureField, EmployeeSettings, FaqItem, ScriptBundle, Section


def build(
    bundle: ScriptBundle | None = None,
    settings: EmployeeSettings | None = None,
    *,
    language: str = "en",
    extra: list[str] | None = None,
    variables: dict[str, str] | None = None,
) -> str:
    return compile_prompt(
        name="Asha",
        role_title="front-desk assistant",
        business_name="Sunrise Dental",
        language=language,
        extra_languages=extra or [],
        bundle=bundle or ScriptBundle(),
        settings=settings or EmployeeSettings(),
        variables=variables,
    )


def test_content_comes_from_the_script_and_conduct_from_the_end_rules() -> None:
    bundle = ScriptBundle(
        welcome_message="Hello from Sunrise Dental.",
        sections=[Section(title="Ask the reason", body="Ask why they are calling.")],
        end_rules="End the call once the visit is booked.",
    )
    prompt = build(bundle)
    flow = prompt.split("# Call flow")[1].split("# Frequently")[0]
    conduct = prompt.split("# Conduct")[1].split("# How closely")[0]
    assert "Hello from Sunrise Dental." in flow and "Ask why they are calling." in flow
    assert "visit is booked" in conduct and "visit is booked" not in flow
    assert "Ask why they are calling." not in conduct


def test_conduct_is_declared_to_override_the_call_flow() -> None:
    assert "override the call flow" in build()


def test_voice_settings_never_reach_the_prompt() -> None:
    plain = build(settings=EmployeeSettings())
    loud = build(
        settings=EmployeeSettings(tts_speed=1.8, ambience="restaurant", ambience_volume=0.9)
    )
    assert plain == loud


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_each_strictness_level_adds_its_own_clause(level: int) -> None:
    prompt = build(ScriptBundle(strictness=level))
    assert STRICTNESS[level] in prompt
    assert all(STRICTNESS[other] not in prompt for other in range(1, 6) if other != level)


def test_the_faq_heading_is_always_present_and_entries_are_listed() -> None:
    assert "# Frequently asked questions" in build(ScriptBundle())
    prompt = build(
        ScriptBundle(faq=[FaqItem(question="Are you open Sunday?", answer="Yes, 10 to 2.")])
    )
    assert "Q: Are you open Sunday?\nA: Yes, 10 to 2." in prompt


def test_pre_call_variables_fill_and_missing_ones_fall_back() -> None:
    bundle = ScriptBundle(
        welcome_message="Hi {{ lead_name }}, calling about {{service}}.",
        pre_call_variables=["lead_name", "service"],
    )
    prompt = build(bundle, variables={"lead_name": "Ravi"})
    assert f"Hi Ravi, calling about {NOT_PROVIDED}." in prompt


def test_undeclared_placeholders_are_left_visible() -> None:
    assert render("Hi {{typo}}", {"typo": "x"}, declared=["name"]) == "Hi {{typo}}"


def test_languages_open_in_the_main_one_and_english_is_always_on() -> None:
    prompt = build(language="te", extra=["hi"])
    assert "Open the call in Telugu" in prompt and "Telugu, Hindi, English" in prompt
    assert "English" in build(language="hi")


def test_toggles_change_only_their_own_clauses() -> None:
    base = build()
    assert "say plainly that you are an AI assistant" not in base
    assert "say plainly that you are an AI assistant" in build(
        settings=EmployeeSettings(ai_acknowledgement=True)
    )
    assert "small natural acknowledgements" in build(settings=EmployeeSettings(style_pack=True))
    info = ScriptBundle(agent_information="We sell solar panels.")
    assert "# About the business" in build(info)
    assert "# Owner's instructions (verbatim)" in build(
        info, EmployeeSettings(power_prompting=True)
    )


def test_end_rules_ask_for_the_end_call_function_and_capture_fields_are_listed() -> None:
    prompt = build(
        ScriptBundle(end_rules="Stop if they are busy."),
        EmployeeSettings(capture=[CaptureField(name="budget", description="Their monthly budget")]),
    )
    assert "call the end_call function" in prompt
    assert "- budget: Their monthly budget" in prompt
    assert "end_call" not in build()
