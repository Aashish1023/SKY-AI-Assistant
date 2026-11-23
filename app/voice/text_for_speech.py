"""Turns streamed answer text into short, speakable sentences.

An answer arrives as a stream of tiny pieces ("Hel", "lo", " wor", ...). Sky should
start speaking after the first sentence, not after the whole answer. Two tools make
that possible:

  * ``clean_for_speech``  removes things that sound awful when read aloud
                          (markdown marks, web addresses, emoji).
  * ``SentenceSplitter``  collects the pieces and hands back each sentence as soon
                          as it is complete. Code blocks are never read aloud.

Nothing here touches audio, so all of it can be tested with plain text.
"""
from __future__ import annotations

import re

# -- cleaning ---------------------------------------------------------------
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
# A web address, not including punctuation that merely ends the sentence.
_URL = re.compile(r"(?:https?://|www\.)\S+?(?=[.,;:!?)]*(?:\s|$))")
_INLINE_CODE = re.compile(r"`([^`]*)`")
_LINE_MARKER = re.compile(r"^\s*(?:[-*+\u2022]\s+|\d+[.)]\s+|#{1,6}\s+|>\s+)")
_BOLD = re.compile(r"(\*\*|__)(.+?)\1")
_ITALIC_STAR = re.compile(r"\*([^*\n]+)\*")
# Underscore emphasis only: snake_case names must keep their underscores.
_ITALIC_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9])_([^_\n]+)_(?![A-Za-z0-9])")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")
_SPACES = re.compile(r"\s+")


def clean_for_speech(text: str) -> str:
    """Make one sentence of text comfortable to hear."""
    text = _MARKDOWN_LINK.sub(r"\1", text)  # [docs](https://...) -> docs
    text = _URL.sub("link", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _LINE_MARKER.sub("", text)  # bullets, numbers, headings, quotes at the start
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

    # -- internals ---------------------------------------------------------
    def _sort_raw_text(self) -> None:
        """Move text from ``_raw`` to ``_text``, dropping everything inside ``` fences."""
        while True:
            if self._in_code:
                end = self._raw.find(_FENCE)
                if end == -1:
                    keep = _trailing_backticks(self._raw)  # may be half of the closing fence
                    self._raw = self._raw[len(self._raw) - keep :] if keep else ""
                    return
                self._raw = self._raw[end + len(_FENCE) :]
                self._in_code = False
                continue

            start = self._raw.find(_FENCE)
            if start == -1:
                hold = _trailing_backticks(self._raw)  # maybe a fence that is still arriving
                self._text += self._raw[: len(self._raw) - hold]
                self._raw = self._raw[len(self._raw) - hold :]
                return
            self._text += self._raw[:start] + "\n"  # the code block ends the sentence before it
            self._raw = self._raw[start + len(_FENCE) :]
            self._in_code = True

    def _extract(self, final: bool) -> list[str]:
        pieces = _BOUNDARY.split(self._text)
        if final:
            complete, self._text = pieces, ""
        else:
            complete, self._text = pieces[:-1], pieces[-1]

        sentences: list[str] = []
        for piece in complete:
            for part in self._cut_into_parts(piece):
                self._consider(part, sentences)

        if not final:
            while len(self._text) > self._max_chars:  # a long run-on: start speaking before it ends
                head, self._text = self._cut_long(self._text)
                self._consider(head, sentences, force=True)

        if final and self._carry:
            self._consider("", sentences, force=True)
        return sentences

    def _consider(self, piece: str, out: list[str], force: bool = False) -> None:
        """Decide whether ``piece`` (joined with any waiting fragment) is ready to be spoken."""
        text = f"{self._carry} {piece}".strip() if self._carry else piece.strip()
        self._carry = ""
        if not text:
            return
        cleaned = clean_for_speech(text)
        if not any(ch.isalnum() for ch in cleaned):
            return  # "---", "***": nothing to say, and nothing worth waiting for
        if not force and (_ends_with_abbreviation(text) or len(cleaned) < self._min_chars):
            self._carry = text  # too short, or "Dr." / "e.g.": wait for more
            return
        out.append(cleaned)

    def _cut_into_parts(self, piece: str) -> list[str]:
        """Split a complete sentence that is longer than ``max_chars`` into several parts."""
        parts = []
        while len(piece) > self._max_chars:
            head, piece = self._cut_long(piece)
            parts.append(head)
        parts.append(piece)
        return parts

    def _cut_long(self, text: str) -> tuple[str, str]:
        """Cut an overly long sentence at its last comma (or space) before ``max_chars``."""
        window = text[: self._max_chars]
        cut = max((window.rfind(mark) + len(mark) for mark in _LONG_BREAKS if window.rfind(mark) > 40), default=-1)
        if cut == -1:
            cut = window.rfind(" ") + 1
        if cut <= 0:
            cut = len(window)
        return text[:cut], text[cut:]