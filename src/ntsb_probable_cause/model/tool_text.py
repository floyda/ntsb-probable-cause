"""Tool text: what a tool result may carry that is not evidence (S3.1 Tasks 3 and 10).

A module of its own, importing nothing from the library, so the code that builds tool text (the
agent's tools and texts) reaches no case record by any import chain: the import-linter contract
"The agent's tools and texts see no case record" counts indirect chains, and ``model/client.py``,
where ``ToolText`` was first written beside ``Payload``, imports ``records.evidence``.
``model/client.py`` re-exports ``ToolText``, so ``from ntsb_probable_cause.model.client import
ToolText`` still works.
"""

from typing import final

# The construction token, never shared with ``Payload``'s: code that holds one cannot make the
# other (``model/client.py``).
_TOOL_TEXT_TOKEN = object()


@final
class ToolText:
    """Non-evidence text for a tool result: numbers, codes, labels, counts, fixed strings.

    Built only by ``ToolText.of``, from a plain ``str``. It is not a ``Payload``, and neither
    can be made from the other: it takes no evidence and no record, and ``Payload`` does not
    accept it. The code that builds it is kept off the case records by an import-linter
    contract, and the boundary test reads every tool text in every request (S3.1 Task 10), so
    what it carries is the loop's own vocabulary and nothing from a case. Immutable, as
    ``Payload`` is: ``__setattr__``/``__delattr__`` refuse any change after construction, and
    ``@final`` closes off subclassing, which would otherwise bypass the construction token.
    """

    __slots__ = ("_text",)
    _text: str

    def __init__(self, text: str, *, _token: object) -> None:
        if _token is not _TOOL_TEXT_TOKEN:
            raise TypeError("ToolText is built only by ToolText.of")
        object.__setattr__(self, "_text", text)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"ToolText is immutable: cannot set {name!r}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"ToolText is immutable: cannot delete {name!r}")

    @classmethod
    def of(cls, text: str) -> ToolText:
        """Wrap a fixed string for a tool result. Anything that is not a ``str`` is refused."""
        if not isinstance(text, str):
            raise TypeError(f"ToolText.of takes a str, not {type(text).__name__}")
        return cls(text, _token=_TOOL_TEXT_TOKEN)

    @property
    def text(self) -> str:
        """The wrapped text."""
        return self._text

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ToolText) and other._text == self._text

    def __hash__(self) -> int:
        return hash(self._text)
