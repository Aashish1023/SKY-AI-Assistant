"""Watch Sky decide what to say.

Streams a sample answer in small pieces (like the language model does) and prints
each sentence the moment it is ready to be spoken.

Run from the project folder:

    .\\.venv\\Scripts\\python.exe scripts\\demo_sentences.py

Try editing SAMPLE below, or change PIECE_SIZE, and run it again.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.voice.text_for_speech import SentenceSplitter  # noqa: E402

PIECE_SIZE = 6  # characters per streamed piece; a real model sends about this much at a time

SAMPLE = """## Setting up your project

Good morning! Here is **what I suggest** for today \U0001F680

1. Open the project folder in VS Code
2. Run the tests with `pytest`
3. Fix anything that fails

Here is a tiny example:

```python
print("hello")
```

That prints a greeting. Dr. Smith wrote a nice guide, see [the docs](https://example.com/docs) for details. Python 3.13 works fine.
"""


def main() -> None:
    splitter = SentenceSplitter()
    pieces = [SAMPLE[i : i + PIECE_SIZE] for i in range(0, len(SAMPLE), PIECE_SIZE)]
    print(f"The answer arrives in {len(pieces)} pieces of {PIECE_SIZE} characters.\n")
    print("piece   sentence ready to speak")
    print("-----   -----------------------")

    count = 0
    for number, piece in enumerate(pieces, start=1):
        for sentence in splitter.feed(piece):
            count += 1
            print(f"{number:5d}   {sentence}")
    for sentence in splitter.flush():
        count += 1
        print(f"{len(pieces):5d}   {sentence}   (released when the answer ended)")

    print(f"\n{count} sentences. Notice: the code block, bullet marks, web address and emoji are never spoken.")


if __name__ == "__main__":
    main()
    