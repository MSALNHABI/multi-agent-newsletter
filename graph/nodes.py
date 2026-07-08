import os
from typing import Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from tavily import TavilyClient
from langgraph.config import get_stream_writer

from graph.prompts import (
    EDITOR_SYSTEM_PROMPT,
    FORMATTER_SYSTEM_PROMPT,
    RESEARCHER_SYSTEM_PROMPT,
    WRITER_SYSTEM_PROMPT,
)
from graph.state import NewsletterState


load_dotenv()


# Environment variables
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.4-mini",
)


if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is missing. Add it to the .env file."
    )
if not TAVILY_API_KEY:
    raise RuntimeError(
        "TAVILY_API_KEY is missing. Add it to the .env file."
    )

# Researcher: factual and consistent
researcher_llm = ChatOpenAI(
    model=OPENAI_MODEL,
    temperature=0.0,
    max_retries=2,
    reasoning_effort="none",
)


# Writer: slightly creative, but still controlled
writer_llm = ChatOpenAI(
    model=OPENAI_MODEL,
    temperature=0.3,
    max_retries=2,
    reasoning_effort="low",
)


# Editor: strict and deterministic
editor_llm = ChatOpenAI(
    model=OPENAI_MODEL,
    temperature=0.0,
    max_retries=2,
    reasoning_effort="medium",
)


# Formatter: deterministic formatting
formatter_llm = ChatOpenAI(
    model=OPENAI_MODEL,
    temperature=0.0,
    max_retries=2,
    reasoning_effort="none",
)

# One shared Tavily client used by the Researcher.
tavily_client = TavilyClient(
    api_key=TAVILY_API_KEY
)


class ResearchOutput(BaseModel):    
    research_notes: list[str] = Field(
        description=(
            "Between 3 and 10 concise factual notes extracted "
            "only from the supplied search results."
        )
    )


class EditorOutput(BaseModel):
    """Structured result expected from the Editor."""

    status: Literal["APPROVED", "REJECTED"] = Field(
        description=(
            "APPROVED only when every factual claim is directly "
            "supported by the research notes. Otherwise REJECTED."
        )
    )

    unsupported_claims: list[str] = Field(
        default_factory=list,
        description=(
            "Exact claims or sentences from the draft that are not "
            "directly supported by the research notes."
        ),
    )

    critique: str = Field(
        default="",
        description=(
            "Specific numbered instructions for fixing the draft. "
            "Return an empty string when approved."
        ),
    )


def get_message_text(response: object) -> str:
    """
    Extract plain text from a LangChain AI message.

    Gemini messages normally expose `.text`; the fallback keeps
    the code compatible with messages whose content is a string.
    """

    text = getattr(response, "text", None)

    if isinstance(text, str) and text.strip():
        return text.strip()

    content = getattr(response, "content", None)

    if isinstance(content, str):
        return content.strip()

    raise RuntimeError(
        "The model returned an unsupported response format."
    )



def format_research_notes(
    research_notes: list[str],
) -> str:
    """Convert research notes into a numbered prompt section."""

    return "\n".join(
        f"{number}. {note}"
        for number, note in enumerate(
            research_notes,
            start=1,
        )
    )


def researcher_node(
    state: NewsletterState,
) -> dict[str, list[str]]:
    stream_writer = get_stream_writer()

    stream_writer(
        {
            "event": "agent_status",
            "agent": "researcher",
            "message": "Researcher is gathering live information.",
        }
    )    
    
    """
    Search the web and convert the results into factual notes.

    Reads:
        topic

    Writes:
        research_notes
    """

    topic = state["topic"].strip()

    if not topic:
        raise ValueError(
            "The research topic cannot be empty."
        )



    topic_lower = topic.lower()

    if "nawader" in topic_lower:
        search_query = (
            f'"Nawader Coffee" {topic}'
        )[:390]
    else:
        search_query = topic[:390]

    try:
        search_response = tavily_client.search(
            query=search_query,
            search_depth="advanced",
            max_results=5,
            include_answer=False,
            include_raw_content=False,
        )
    except Exception as error:
        raise RuntimeError(
            f"The live search failed for topic '{topic}': {error}"
        ) from error

    search_results = search_response.get(
        "results",
        [],
    )

    if not search_results:
        raise RuntimeError(
            f"No search results were found for: {topic}"
        )

    source_blocks: list[str] = []

    for search_result in search_results:
        title = search_result.get(
            "title",
            "Unknown title",
        )

        url = search_result.get(
            "url",
            "Unknown URL",
        )

        content = search_result.get(
            "content",
            "",
        ).strip()

        if not content:
            continue

        source_number = len(source_blocks) + 1

        source_blocks.append(
            (
                f"Source {source_number}\n"
                f"Title: {title}\n"
                f"URL: {url}\n"
                f"Content:\n{content}"
            )
        )

    if not source_blocks:
        raise RuntimeError(
            "Search results were returned, but they "
            "contained no usable content."
        )

    source_material = "\n\n---\n\n".join(
        source_blocks
    )

    researcher_prompt = f"""
Research topic:
{topic}

Web search results:
{source_material}

Extract between 3 and 10 concise factual bullet points.

Requirements:
- Use only information explicitly stated in the search results.
- Write one factual claim per bullet point.
- Start every note with its source number, such as "Source 1:".
- Preserve names, numbers, dates, comparisons, and qualifications.
- Do not infer missing information.
- Do not combine unrelated facts into a new conclusion.
- Do not give opinions, recommendations, or marketing claims.
- Do not write article prose.
- Exclude unclear, contradictory, or irrelevant claims.
""".strip()

    structured_researcher = researcher_llm.with_structured_output(
        ResearchOutput,
        method="json_schema",
        strict=True,
    )

    raw_result = structured_researcher.invoke(
        [
            {
                "role": "system",
                "content": RESEARCHER_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": researcher_prompt,
            },
        ]
    )

    result = (
        raw_result
        if isinstance(raw_result, ResearchOutput)
        else ResearchOutput.model_validate(raw_result)
    )

    cleaned_notes = [
        note.strip()
        for note in result.research_notes
        if note.strip()
    ]

    if len(cleaned_notes) < 3:
        raise ValueError(
        "Not enough relevant information was found for the "
        "exact topic. If this is an internal Nawader event, "
        "provide the approved event details."
        )

    return {
        "research_notes": cleaned_notes[:10]
    }


def writer_node(
    state: NewsletterState,
) -> dict[str, str | int]:
    """
    Write the first draft or revise the current draft.

    Reads:
        topic
        research_notes
        current_draft
        critique
        revision_count
        draft_history

    Writes:
        current_draft
        revision_count
        draft_history
    """

    topic = state["topic"].strip()
    language = state.get(
    "language",
    "en",
    )
    if language == "ar":
        language_instruction = """
    Write the complete article in Modern Standard Arabic.

    Requirements:
    - Write the headline, subheadings, and paragraphs in Arabic.
    - Use natural and clear Arabic suitable for a newsletter.
    - Keep names, numbers, measurements, and technical terms accurate.
    - Do not add English explanations unless a proper name requires them.
    """.strip()

    else:
        language_instruction = """
    Write the complete article in clear English.

    Requirements:
    - Write the headline, subheadings, and paragraphs in English.
    - Use natural and clear English suitable for a newsletter.
    """.strip()
        
    research_notes = state.get(
        "research_notes",
        [],
    )
    critique = state.get(
        "critique",
        "",
    ).strip()
    current_draft = state.get(
        "current_draft",
        "",
    ).strip()

    stream_writer = get_stream_writer()

    revision_count = state.get(
        "revision_count",
        0,
    )

    stream_writer(
        {
            "event": "agent_status",
            "agent": "writer",
            "message": (
                f"Writer is preparing draft "
                f"{revision_count + 1}."
            ),
        }
    )
    if not topic:
        raise ValueError(
            "The Writer cannot work without a topic."
        )

    if not research_notes:
        raise ValueError(
            "The Writer cannot work without research notes."
        )

    formatted_notes = format_research_notes(
        research_notes
    )

    if critique and current_draft:
        writer_prompt = f"""
    Newsletter topic:
    {topic}

    Output language:
    {language_instruction}

    Research notes — the only allowed source of facts:
    {formatted_notes}

    Current article draft:
    {current_draft}

    Editor's critique:
    {critique}

    Rewrite the complete article.

    Requirements:
    - Address every point in the Editor's critique.
    - Use only facts contained in the research notes.
    - Do not invent names, numbers, dates, quotations, or claims.
    - Do not invent facts about Nawader Coffee.
    - Keep the article neutral, newsworthy, and suitable for
    Nawader Coffee's newsletter audience.
    - Do not mention the Researcher, Editor, workflow, prompt,
    sources, or research notes.
    - Return the complete improved article, not a list of changes.
    """.strip()
        
    else:
        writer_prompt = f"""
    Newsletter topic:
    {topic}

    Output language:
    {language_instruction}

    Research notes — the only allowed source of facts:
    {formatted_notes}

    Write the first complete newsletter article.

    Requirements:
    - Use only facts contained in the research notes.
    - Do not invent names, numbers, dates, quotations, or claims.
    - Do not invent facts about Nawader Coffee.
    - Keep the article neutral, newsworthy, and suitable for
    Nawader Coffee's newsletter audience.
    - Do not mention the Researcher, Editor, workflow, prompt,
    sources, or research notes.
    - Return article prose only.
    """.strip()

    response = writer_llm.invoke(
        [
            {
                "role": "system",
                "content": WRITER_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": writer_prompt,
            },
        ]
    )

    new_draft = get_message_text(response)

    if not new_draft:
        raise RuntimeError(
            "The Writer returned an empty article draft."
        )

    new_revision_count = revision_count + 1

    

    return {
        "current_draft": new_draft,
        "revision_count": new_revision_count,
    }


def editor_node(
    state: NewsletterState,
) -> dict[str, str]:
    stream_writer = get_stream_writer()

    stream_writer(
        {
            "event": "agent_status",
            "agent": "editor",
            "message": "Editor is reviewing the latest draft.",
        }
    )
    """
    Review the Writer's latest draft.

    Reads:
        topic
        current_draft
        research_notes
        revision_count
        review_history

    Writes:
        status
        critique
        review_history
    """

    current_draft = state.get(
        "current_draft",
        "",
    ).strip()
    research_notes = state.get(
        "research_notes",
        [],
    )

    if not current_draft:
        raise ValueError(
            "The Editor cannot review an empty draft."
        )

    if not research_notes:
        raise ValueError(
            "The Editor cannot review without research notes."
        )

    formatted_notes = format_research_notes(
        research_notes
    )

    editor_prompt = f"""
    Research notes — the only allowed source of facts:
    {formatted_notes}

    Article draft:
    {current_draft}

    Review the article according to these criteria:

    1. Factual grounding:
    Every factual claim must be traceable to the research notes.

    2. Tone:
    The article must be neutral and newsworthy.

    3. Brand relevance:
    The article must be meaningfully relevant to a Nawader Coffee
    newsletter without inventing facts about Nawader Coffee.

    Return APPROVED only if the article passes all three criteria.

    If rejected, provide specific and actionable feedback that the
    Writer can use in the next revision.
    """.strip()

    structured_editor = editor_llm.with_structured_output(
        EditorOutput,
        method="json_schema",
    )

    raw_result = structured_editor.invoke(
        [
            {
                "role": "system",
                "content": EDITOR_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": editor_prompt,
            },
        ]
    )

    result = (
        raw_result
        if isinstance(raw_result, EditorOutput)
        else EditorOutput.model_validate(raw_result)
    )

    unsupported_claims = [
        claim.strip()
        for claim in result.unsupported_claims
        if claim.strip()
    ]

    critique = result.critique.strip()

    # If unsupported claims exist, rejection is mandatory.
    status: Literal["APPROVED", "REJECTED"]

    if unsupported_claims:
        status = "REJECTED"
    else:
        status = result.status

    if status == "REJECTED" and not critique:
        critique = "\n".join(
            (
                f"{number}. Remove or rewrite this "
                f'unsupported claim: "{claim}"'
            )
            for number, claim in enumerate(
                unsupported_claims,
                start=1,
            )
        )

    if status == "REJECTED" and not critique:
        raise RuntimeError(
            "The Editor rejected the article but did not "
            "provide an actionable critique."
        )

    if status == "APPROVED":
        critique = ""

    return {
        "status": status,
        "critique": critique,
    }


def formatter_node(
    state: NewsletterState,
) -> dict[str, str]:
    stream_writer = get_stream_writer()

    stream_writer(
        {
            "event": "agent_status",
            "agent": "formatter",
            "message": "Formatter is preparing the final article.",
        }
    )
    """
    Convert the final article draft into readable Markdown.

    Reads:
        topic
        current_draft

    Writes:
        article_markdown
    """

    current_draft = state.get(
        "current_draft",
        "",
    ).strip()

 

    if not current_draft:
        raise ValueError(
            "The Formatter cannot format an empty draft."
        )

    formatter_prompt = f"""
    Article draft:
    {current_draft}

    Format the draft as highly readable Markdown.

    Requirements:
    - Add one clear Markdown headline.
    - Add useful subheadings where appropriate.
    - Use short, readable paragraphs.
    - Preserve every fact and the original meaning.
    - Do not add, remove, correct, or reinterpret information.
    - Return Markdown only.
    """.strip()

    response = formatter_llm.invoke(
        [
            {
                "role": "system",
                "content": FORMATTER_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": formatter_prompt,
            },
        ]
    )

    article_markdown = get_message_text(response)

    if not article_markdown:
        raise RuntimeError(
            "The Formatter returned empty Markdown."
        )
    if not article_markdown.startswith("# "):
        raise RuntimeError(
        "The Formatter did not return a Markdown headline."
    )

    return {
        "article_markdown": article_markdown
    }
