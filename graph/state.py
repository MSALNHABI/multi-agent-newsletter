from typing import Literal, TypedDict


class DraftVersion(TypedDict):
    """
    One version produced by the Writer.
    """

    revision_number: int
    draft: str


class ReviewRecord(TypedDict):
    """
    One review produced by the Editor.
    """

    revision_number: int
    status: Literal["APPROVED", "REJECTED"]
    critique: str


from typing import Literal, TypedDict


class NewsletterState(TypedDict):
    """
    Shared state passed through every LangGraph node.
    """

    # User input: the newsletter subject.
    topic: str

    # Selected article output language.
    language: Literal["en", "ar"]


    # Researcher output: the only factual source allowed
    # for the Writer and Editor.
    research_notes: list[str]

    # Writer output: the latest complete article draft.
    current_draft: str

    # Editor output: actionable feedback for the next
    # Writer revision. Empty on the first Writer pass.
    critique: str

    # Editor verdict used by the Router.
    status: Literal["APPROVED", "REJECTED"]

    # Number of Writer passes completed.
    revision_count: int

    # Formatter output returned by the API.
    article_markdown: str   