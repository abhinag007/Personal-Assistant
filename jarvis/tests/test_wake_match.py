"""Fuzzy wake-word matching tests (§3) — tolerate STT mishearings of 'Jarvis'."""
import pytest

from jarvis.voice.activity import split_on_wake, word_is_wake

WAKE = ("jarvis",)


@pytest.mark.parametrize("word", ["jarvis", "Jarvis", "Jervis", "Jaarvis", "Jarvish", "Javis", "jarvis."])
def test_mishearings_match(word):
    assert word_is_wake(word, WAKE) is True


@pytest.mark.parametrize("word", ["hello", "service", "harvest", "coffee", "yourself"])
def test_unrelated_words_dont_match(word):
    assert word_is_wake(word, WAKE) is False


def test_split_returns_command_after_wake():
    matched, cmd = split_on_wake("Hey Jervis what's the time", WAKE)
    assert matched is True
    assert cmd == "what's the time"


def test_split_bare_wake_has_no_command():
    matched, cmd = split_on_wake("hello Jaarvis", WAKE)
    assert matched is True
    assert cmd == ""


def test_split_no_wake():
    matched, cmd = split_on_wake("here is your wish", WAKE)
    assert matched is False
    assert cmd == ""
