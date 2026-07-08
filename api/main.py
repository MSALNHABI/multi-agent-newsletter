import logging
import json
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from graph.build_graph import newsletter_graph


from collections.abc import Generator
from fastapi.responses import StreamingResponse
from graph.state import NewsletterState

logger = logging.getLogger(__name__)


app = FastAPI(
    title="Nawader Newsletter API",
    description=(
        "A multi-agent newsletter workflow built with "
        "LangGraph, OpenAI, and live web research."    ),
    version="1.0.0",
)


class ArticleRequest(BaseModel):
    """
    Request body received from Streamlit or another client.
    """

    topic: str = Field(
        description="The subject of the newsletter article."
    )

    language: Literal["en", "ar"] = Field(
        default="en",
        description=(
            "Output language: en for English or ar for Arabic."
        ),
    )


class ArticleResponse(BaseModel):
    """
    Final API response after the LangGraph workflow finishes.
    """

    article_markdown: str

    research_notes: list[str]

    revision_count: int

    final_status: Literal[
        "APPROVED",
        "REVISION_CAP_REACHED",
    ]

    final_critique: str


@app.get("/")
def root() -> dict[str, str]:
    """
    Simple route used to confirm that the API is running.
    """

    return {
        "message": "Nawader Newsletter API is running."
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    """
    Health-check route.
    """

    return {
        "status": "healthy"
    }


@app.post(
    "/generate",
    response_model=ArticleResponse,
)
def generate_article(
    request: ArticleRequest,
) -> ArticleResponse:
    """
    Generate a newsletter article using the compiled graph.
    """

    topic = request.topic.strip()

    # The assignment specifically requires HTTP 400
    # when the topic is empty.
    if not topic:
        raise HTTPException(
            status_code=400,
            detail="Topic cannot be empty.",
        )

    initial_state = {
        "topic": topic,
        "language": request.language,
        "research_notes": [],
        "current_draft": "",
        "critique": "",
        "status": "REJECTED",
        "revision_count": 0,
        "article_markdown": "",
    }

    try:
        # newsletter_graph was already compiled when
        # graph.build_graph was imported.
        result = newsletter_graph.invoke(
            initial_state
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except Exception as error:
        logger.exception(
            "Newsletter generation failed."
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Article generation failed. "
                "Check the API terminal for details."
            ),
        ) from error

    editor_status = result["status"]
    revision_count = result["revision_count"]

    if editor_status == "APPROVED":
        final_status = "APPROVED"

    elif (
        editor_status == "REJECTED"
        and revision_count >= 3
    ):
        final_status = "REVISION_CAP_REACHED"

    else:
        logger.error(
            "Workflow ended in an unexpected state: "
            "status=%s, revision_count=%s",
            editor_status,
            revision_count,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "The workflow ended before approval "
                "or the revision safety cap."
            ),
        )

    return ArticleResponse(
        article_markdown=result["article_markdown"],
        research_notes=result["research_notes"],
        revision_count=revision_count,
        final_status=final_status,
        final_critique=result["critique"],
    
    )
def json_line(
    payload: dict,
) -> str:
    """
    Convert an event into one JSON line for streaming.
    """

    return (
        json.dumps(
            payload,
            ensure_ascii=False,
        )
        + "\n"
    )


@app.post("/generate-stream")
def generate_article_stream(
    request: ArticleRequest,
) -> StreamingResponse:
    """
    Stream workflow progress and return the final article
    as the last event.
    """

    topic = request.topic.strip()

    if not topic:
        raise HTTPException(
            status_code=400,
            detail="The newsletter topic cannot be empty.",
        )

    initial_state: NewsletterState = {
        "topic": topic,
        "language": request.language,
        "research_notes": [],
        "current_draft": "",
        "critique": "",
        "status": "REJECTED",
        "revision_count": 0,
        "article_markdown": "",
    }

    def event_generator() -> Generator[str, None, None]:
        current_state = dict(initial_state)

        # First event appears immediately.
        yield json_line(
            {
                "type": "progress",
                "node": "researcher",
                "message": (
                    "Researcher is searching live sources..."
                ),
                "level": "info",
                "revision_count": 0,
            }
        )

        try:
            for part in newsletter_graph.stream(
                initial_state,
                stream_mode="updates",
                version="v2",
            ):
                if part["type"] != "updates":
                    continue

                for node_name, update in part["data"].items():
                    if not isinstance(update, dict):
                        continue

                    current_state.update(update)

                    revision_count = int(
                        current_state.get(
                            "revision_count",
                            0,
                        )
                    )

                    # -------------------------------------
                    # Researcher completed
                    # -------------------------------------
                    if node_name == "researcher":
                        yield json_line(
                            {
                                "type": "progress",
                                "node": "researcher",
                                "message": (
                                    "Research complete. "
                                    "Writer is preparing pass 1..."
                                ),
                                "level": "info",
                                "revision_count": 0,
                            }
                        )

                    # -------------------------------------
                    # Writer completed a pass
                    # -------------------------------------
                    elif node_name == "writer":
                        yield json_line(
                            {
                                "type": "progress",
                                "node": "writer",
                                "message": (
                                    f"Writer pass {revision_count} "
                                    "complete. Editor is reviewing..."
                                ),
                                "level": "info",
                                "revision_count": revision_count,
                            }
                        )

                    # -------------------------------------
                    # Editor completed a review
                    # -------------------------------------
                    elif node_name == "editor":
                        editor_status = str(
                            current_state.get(
                                "status",
                                "REJECTED",
                            )
                        ).upper()

                        if editor_status == "APPROVED":
                            message = (
                                f"Editor approved pass "
                                f"{revision_count}. "
                                "Formatter is preparing "
                                "the final article..."
                            )

                            level = "success"

                        elif revision_count >= 3:
                            message = (
                                "Revision cap reached after "
                                f"{revision_count} Writer passes. "
                                "Formatter is preparing the best "
                                "available draft..."
                            )

                            level = "warning"

                        else:
                            message = (
                                f"Editor rejected pass "
                                f"{revision_count}. "
                                "Writer is revising..."
                            )

                            level = "warning"

                        yield json_line(
                            {
                                "type": "progress",
                                "node": "editor",
                                "message": message,
                                "level": level,
                                "revision_count": revision_count,
                                "editor_status": editor_status,
                                "critique": current_state.get(
                                    "critique",
                                    "",
                                ),
                            }
                        )

                    # -------------------------------------
                    # Formatter completed
                    # -------------------------------------
                    elif node_name == "formatter":
                        yield json_line(
                            {
                                "type": "progress",
                                "node": "formatter",
                                "message": (
                                    "Formatting complete. "
                                    "The final article is ready."
                                ),
                                "level": "success",
                                "revision_count": revision_count,
                            }
                        )

            editor_status = str(
                current_state.get(
                    "status",
                    "REJECTED",
                )
            ).upper()

            revision_count = int(
                current_state.get(
                    "revision_count",
                    0,
                )
            )

            if editor_status == "APPROVED":
                final_status = "APPROVED"

            elif (
                editor_status == "REJECTED"
                and revision_count >= 3
            ):
                final_status = "REVISION_CAP_REACHED"

            else:
                raise RuntimeError(
                    "The workflow ended in an unexpected state."
                )

            final_result = {
                "article_markdown": current_state.get(
                    "article_markdown",
                    "",
                ),
                "research_notes": current_state.get(
                    "research_notes",
                    [],
                ),
                "revision_count": revision_count,
                "final_status": final_status,
                "final_critique": current_state.get(
                    "critique",
                    "",
                ),
            }

            yield json_line(
                {
                    "type": "result",
                    "data": final_result,
                }
            )

        except Exception as error:
            yield json_line(
                {
                    "type": "error",
                    "message": str(error),
                }
            )

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )