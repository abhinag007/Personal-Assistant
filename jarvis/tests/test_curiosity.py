"""Curiosity tests (§8) — asks the next unknown thing, once each, stops when known."""
from jarvis.brain.curiosity import DESIRED_FIELDS, asked_flag, next_curiosity, missing_topics
from jarvis.brain.persona import build_system_prompt


def test_next_is_name_when_nothing_known():
    field, question = next_curiosity({})
    assert field == "name"
    assert "call you" in question.lower()


def test_skips_known_field():
    field, _ = next_curiosity({"name": "Abhi"})
    assert field == "about"  # moved on to the next unknown


def test_skips_already_asked_field():
    # Name unknown but already asked once → don't ask again; move on.
    profile = {asked_flag("name"): "1"}
    field, _ = next_curiosity(profile)
    assert field == "about"


def test_nothing_to_ask_when_all_known_or_asked():
    profile = {}
    for key, _ in DESIRED_FIELDS:
        profile[key] = "x"
    assert next_curiosity(profile) is None


def test_missing_topics_shrink_as_learned():
    assert len(missing_topics({})) == len(DESIRED_FIELDS)
    assert len(missing_topics({"name": "Abhi"})) == len(DESIRED_FIELDS) - 1


def test_persona_has_curious_tone_for_new_user():
    prompt = build_system_prompt(user_name=None, profile_facts={})
    assert "curious" in prompt.lower()
