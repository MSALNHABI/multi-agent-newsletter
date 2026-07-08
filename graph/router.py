from graph.state import NewsletterState


MAX_REVISIONS = 3


def route_after_editor(
    state: NewsletterState,
) -> str:
    """
    Decide what happens after the Editor reviews the draft.

    Reads:
        status
        revision_count

    Routes:
        APPROVED -> formatter
        REJECTED and revision_count < 3 -> writer
        REJECTED and revision_count >= 3 -> formatter
    """

    status = state["status"]
    revision_count = state["revision_count"]

    if status == "APPROVED":
        return "formatter"

    if revision_count >= MAX_REVISIONS:
        return "formatter"

    return "writer"