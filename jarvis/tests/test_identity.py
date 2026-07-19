"""Identity learning tests (§8) — name extracted from conversation, not hardcoded."""
from jarvis.brain.identity import extract_name, extract_preferred_address


class TestExtractName:
    def test_my_name_is(self):
        assert extract_name("Hi, my name is Abhi") == "Abhi"
        assert extract_name("my name is Abhijeet Nag") == "Abhijeet Nag"
        assert extract_name("my name is not sir it's Abhijeet Nag") == "Abhijeet Nag"

    def test_call_me(self):
        assert extract_name("you can call me Sam please") == "Sam"
        assert extract_name("call me sir") is None

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


class TestPreferredAddress:
    def test_refer_to_me_as(self):
        assert extract_preferred_address("please refer to me as sir") == "Sir"
        assert extract_preferred_address("address me as boss") == "Boss"

    def test_call_me_honorific(self):
        assert extract_preferred_address("call me sir") == "Sir"

    def test_call_me_real_name_not_address(self):
        assert extract_preferred_address("call me Neo") is None
