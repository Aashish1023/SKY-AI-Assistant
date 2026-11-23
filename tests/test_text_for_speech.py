"""Tests for app.voice.text_for_speech: cleaning text and splitting a stream into sentences."""
import pytest

from app.voice.text_for_speech import SentenceSplitter, clean_for_speech


def split_all(pieces, **options):
    """Feed pieces one by one, then flush. Returns every sentence, in order."""
    splitter = SentenceSplitter(**options)
    sentences = []
    for piece in pieces:
        sentences += splitter.feed(piece)
    return sentences + splitter.flush()


# ------------------------------------------------------------------ cleaning
@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("**Important:** read this", "Important: read this"),
        ("This is *really* good", "This is really good"),
        ("This is _also_ good", "This is also good"),
        ("Use `pip install` first", "Use pip install first"),
        ("## A heading", "A heading"),
        ("- a bullet point", "a bullet point"),
        ("3. a numbered point", "a numbered point"),
        ("> a quoted line", "a quoted line"),
        ("See [the docs](https://example.com/docs) now", "See the docs now"),
        ("Visit https://example.com/page for more", "Visit link for more"),
        ("Visit https://example.com/page.", "Visit link."),  # the full stop stays
        ("Great job \U0001F389\U0001F680", "Great job"),
        ("  too    many   spaces  ", "too many spaces"),
        ("call my_function_name now", "call my_function_name now"),  # snake_case is kept intact
        ("It costs 3.14 dollars", "It costs 3.14 dollars"),
    ],
)
def test_clean_for_speech(raw, spoken):
    assert clean_for_speech(raw) == spoken


# ----------------------------------------------------------------- splitting
def test_sentences_are_released_as_soon_as_they_are_complete():
    splitter = SentenceSplitter()

    assert splitter.feed("I am Sky, your") == []  # nothing complete yet
    assert splitter.feed(" assistant.") == []  # a full stop alone is not enough: it might be "3.14"
    assert splitter.feed(" How can") == ["I am Sky, your assistant."]  # the space proves the sentence is over
    assert splitter.feed(" I help you today? ") == ["How can I help you today?"]
    assert splitter.flush() == []


def test_a_sentence_end_needs_a_space_after_it():
    splitter = SentenceSplitter()

    assert splitter.feed("This sentence ends here.") == []  # might be "here.com" or "3.14": wait
    assert splitter.feed(" And another one") == ["This sentence ends here."]
    assert splitter.flush() == ["And another one"]


def test_flush_returns_the_unfinished_last_sentence():
    assert split_all(["No full stop at the end"]) == ["No full stop at the end"]


@pytest.mark.parametrize("text", ["Python 3.13 is installed on this machine. Next", "Open example.com in your browser. Done"])
def test_decimals_and_web_addresses_do_not_split_a_sentence(text):
    first = split_all([text])[0]

    assert first.endswith(("machine.", "browser."))


def test_abbreviations_do_not_end_a_sentence():
    assert split_all(["Dr. Smith is in the building. Welcome to the lab."]) == [
        "Dr. Smith is in the building.",
        "Welcome to the lab.",
    ]


def test_tiny_fragments_join_the_next_sentence():
    assert split_all(["Yes. I will do that for you now."]) == ["Yes. I will do that for you now."]


def test_line_breaks_separate_list_items_and_the_bullets_are_not_spoken():
    text = "Here is the list:\n- first item in the list\n- second item in the list\n"

    assert split_all([text]) == ["Here is the list:", "first item in the list", "second item in the list"]


def test_a_very_long_sentence_is_cut_at_a_comma_so_speech_can_start_sooner():
    long_text = ("this is a long run on sentence that keeps going, " * 8).strip()

    sentences = split_all([long_text], max_chars=100)

    assert len(sentences) > 1
    assert all(len(s) <= 100 for s in sentences)
    assert " ".join(sentences).replace(",", "").split() == long_text.replace(",", "").split()  # nothing lost


def test_text_with_nothing_to_say_is_skipped():
    assert split_all(["---\n***\nReal words are here.\n"]) == ["Real words are here."]


# ------------------------------------------------------------------ code blocks
CODE_ANSWER = "Here is the code:\n```python\nprint('hello')\nx = 3.14\n```\nThat prints a greeting."


def test_code_blocks_are_never_read_aloud():
    assert split_all([CODE_ANSWER]) == ["Here is the code:", "That prints a greeting."]


def test_code_fences_are_recognised_even_when_split_across_pieces():
    pieces = ["Here is the code:\n`", "`", "`python\nprint('hello')\n`", "`", "`\nThat prints a greeting."]

    assert split_all(pieces) == ["Here is the code:", "That prints a greeting."]


def test_an_unclosed_code_block_is_dropped_at_the_end():
    assert split_all(["Look at this code now:\n```\nwhile True:\n    pass"]) == ["Look at this code now:"]


def test_a_single_backtick_in_text_is_just_text():
    assert split_all(["Use `pip` to install it."]) == ["Use pip to install it."]


# --------------------------------------------------- the key property of streaming
SAMPLES = [
    "Hello there. I am Sky, your assistant. How can I help you today?",
    "Here is a plan:\n1. Open the project folder\n2. Run the tests\n3. Fix the failing one\nThat is all.",
    CODE_ANSWER,
    "Dr. Smith says Python 3.13 is great. See [the docs](https://example.com/docs). Done! Really?",
    "**Bold** and *italic* and `code`, plus a link https://example.com/x. The end.",
]


@pytest.mark.parametrize("text", SAMPLES)
@pytest.mark.parametrize("size", [1, 2, 3, 7, 50])
def test_the_result_does_not_depend_on_how_the_text_arrives(text, size):
    """Tokens arrive in unpredictable pieces. The sentences must always come out the same."""
    all_at_once = split_all([text])
    in_pieces = split_all([text[i : i + size] for i in range(0, len(text), size)])

    assert in_pieces == all_at_once
    assert all_at_once  # and there was something to say


def test_reset_forgets_everything():
    splitter = SentenceSplitter()
    splitter.feed("An unfinished sentence that never ends")
    splitter.reset()

    assert splitter.flush() == []
    assert splitter.feed("A fresh start begins right here. ") == ["A fresh start begins right here."]