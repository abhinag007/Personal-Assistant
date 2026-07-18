"""Identity learning tests (§8) — name extracted from conversation, not hardcoded."""
from jarvis.brain.identity import extract_name


class TestExtractName:
    def test_my_name_is(self):
        assert extract_name("Hi, my name is Abhi") == "Abhi"

    def test_call_me(self):
        assert extract_name("you can call me Sam please") == "Sam"

    def test_im_name(self):
        assert extract_name("I'm Priya, nice to meet you") == "Priya"

    def test_i_am_name(self):
        assert extract_name("I am Ravi") == "Ravi"

    def test_lowercase_is_capitalized(self):
        assert extract_name("my name is john") == "John"

    def test_rejects_feeling_statements(self):
        # These must NOT be read as names.
        assert extract_name("I'm tired") is None
        assert extract_name("I am busy right now") is None
        assert extract_name("I'm just looking") is None

    def test_no_name_returns_none(self):
        assert extract_name("what's the weather today?") is None
        assert extract_name("") is None
