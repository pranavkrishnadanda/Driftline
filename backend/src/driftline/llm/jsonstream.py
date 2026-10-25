"""Stream one top-level string field out of a JSON object while it is being generated.

Structured output arrives as JSON text deltas. The draft's `answer` field is the part
a person should see token by token, so this decodes just that string as it grows,
including escapes split across deltas, and ignores everything else.
"""

import json
import re

_HIGH_SURROGATE = re.compile(r"\\u[dD][89abAB][0-9a-fA-F]{2}")


class JsonStringFieldStreamer:
    def __init__(self, field: str) -> None:
        self._key = re.compile(r'(?<!\\)"' + re.escape(field) + r'"\s*:\s*"')
        self._buf = ""
        self._pos: int | None = None  # index of the next undecoded char of the value
        self.done = False

    def feed(self, delta: str) -> str:
        """Add a delta; return the newly decoded part of the field's value (maybe "")."""
        self._buf += delta
        if self.done:
            return ""
        if self._pos is None:
            match = self._key.search(self._buf)
            if match is None:
                return ""
            self._pos = match.end()
        out: list[str] = []
        buf, i = self._buf, self._pos
        while i < len(buf):
            ch = buf[i]
            if ch == '"':
                self.done = True
                break
            if ch != "\\":
                out.append(ch)
                i += 1
                continue
            if i + 1 >= len(buf):
                break  # the escape continues in the next delta
            width = 6 if buf[i + 1] == "u" else 2
            if width == 6 and _HIGH_SURROGATE.match(buf, i):
                width = 12  # a surrogate pair decodes as one character
            if i + width > len(buf):
                break
            seq = buf[i : i + width]
            try:
                out.append(json.loads(f'"{seq}"'))
            except json.JSONDecodeError:
                out.append(seq)
            i += width
        self._pos = i
        return "".join(out)
