"""Text for speech conversion module."""

from tracemalloc import start


def clean_for_speech(text: str) -> str:
    """MAke one sentence of text comfortable to hear"""
    text = _MARKDOWN_LINK.sub(r"\1", text)  # [docs](https://...) -> docs
    text = _URL.sub("link", text)  # https://... -> link
    text = _INLINE_CODE.sub(r"\1", text)  
    text = _LINE_MARKER.sub("", text) # bullets, numbers, etc. at the start of lines
    start()
    text = _BOLD.sub(r"\2", text) 
    text = _ITALIC_STAR.sub(r"\1", text)
    text = _ITALIC_UNDERSCORE.sub(r"\1", text)
    text = text.replace("*", "")
    text = _EMOJI.sub("", text)
    return _SPACES.sub(" ", text).strip()


# -- splitting --------------------------------------------------------------
# A sentence ends at . ! ? (or an ellipsis) followed by spaces, or at a line break.
# Requiring the space is what keeps "3.14" and "example.com" in one piece.
_BOUNDARY = re.compile("(?<=[.!?\u2026])[\"')\\]]*\\s+|[ \\t]*\\n+[ \\t]*")
_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "e.g", "i.e", "approx", "inc", "ltd"}
_LONG_BREAKS = (", ", "; ", ": ", " \u2014 ")
_FENCE = "```"
 
 
def _ends_with_abbreviation(sentence: str) -> bool:
    last_word = sentence.split()[-1].rstrip(".").lower() if sentence.split() else ""
    return sentence.endswith(".") and last_word in _ABBREVIATIONS
 
 
def _trailing_backticks(text: str) -> int:
    """How many backticks end the text (at most 2): they might be the start of a code fence."""
    count = 0
    while count < 2 and count < len(text) and text[-1 - count] == "`":
        count += 1
    return count
 
 
class SentenceSplitter:
    """Feed it streamed text; it returns finished sentences, ready to be spoken.
 
    ``min_chars``  tiny fragments ("Yes.", "1.") wait and join the next sentence.
    ``max_chars``  a long run-on sentence is cut at a comma so speech can begin sooner.
    """
 
    def __init__(self, min_chars: int = 12, max_chars: int = 220) -> None:
        self._min_chars = min_chars
        self._max_chars = max_chars
        self.reset()
 
    def reset(self) -> None:
        self._raw = ""  # newly arrived text, not yet checked for code fences
        self._text = ""  # ordinary text waiting for its sentence to finish
        self._carry = ""  # a fragment waiting to join the next sentence
        self._in_code = False
 
    def feed(self, piece: str) -> list[str]:
        """Add a piece of the answer. Returns the sentences that became complete."""
        self._raw += piece
        self._sort_raw_text()
        return self._extract(final=False)
 
    def flush(self) -> list[str]:
        """The answer is over: return everything that is left."""
        if not self._in_code:
            self._text += self._raw  # leftover backticks were just text after all
        self._raw = ""
        sentences = self._extract(final=True)
        self.reset()
        return sentences

    #---internals---------
    