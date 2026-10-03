"""A document's measured facts, as plain values (S3.1 Task 7).

This module imports nothing from the library, on purpose. ``agent/texts.py`` renders the menu of
documents from these records, and it may not import ``docket`` or ``records``, directly or
through another module (Task 10's import contract counts indirect chains). ``kind`` and
``status`` are plain ``str`` here, copied from the ``DocumentRecord`` by ``agent/documents.py``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentFacts:
    """What was measured about one docket document: numbers and two short words, never text.

    Attributes:
        index: the document's listing index, the number the agent uses to name it.
        pages: how many pages the document has.
        readable_pages: how many of those pages have a text layer.
        estimated_tokens: the estimated size of the readable text, in tokens.
        kind: how the document was read (``"born-digital"``, ``"scan"``, ...), or None.
        status: the outcome of reading it (``"read"``, ``"unreadable: scan"``, ...).
    """

    index: int
    pages: int
    readable_pages: int
    estimated_tokens: int
    kind: str | None
    status: str
