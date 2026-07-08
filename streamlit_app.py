import json
import os
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

from export_utils import (
    EXPORT_FORMATS,
    prepare_export,
)


load_dotenv()


# =========================================================
# Page configuration
# =========================================================

st.set_page_config(
    page_title="Nawader Newsletter",
    page_icon="☕",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =========================================================
# Paths and external CSS
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
CSS_PATH = BASE_DIR / "assets" / "style.css"


@st.cache_data
def load_css() -> str:
    """
    Load the external CSS file.
    """

    if not CSS_PATH.exists():
        raise RuntimeError(
            f"CSS file was not found: {CSS_PATH}"
        )

    return CSS_PATH.read_text(
        encoding="utf-8"
    )


st.markdown(
    f"<style>{load_css()}</style>",
    unsafe_allow_html=True,
)


# =========================================================
# API configuration
# =========================================================

API_STREAM_URL = os.getenv(
    "NEWSLETTER_API_URL",
    "http://127.0.0.1:8000/generate-stream",
)


# =========================================================
# Export helpers
# =========================================================

@st.cache_data(
    show_spinner=False
)
def build_export_file(
    article_markdown: str,
    topic: str,
    language: str,
    export_format: str,
) -> tuple[bytes, str, str]:
    """
    Prepare and cache the selected article export.
    """

    return prepare_export(
        article_markdown=article_markdown,
        topic=topic,
        language=language,
        export_format=export_format,
    )


# =========================================================
# UI helpers
# =========================================================

def update_status_display(
    placeholder,
    message: str,
    level: str = "info",
) -> None:
    """
    Replace the current workflow status message.
    """

    if level == "success":
        placeholder.success(message)

    elif level == "warning":
        placeholder.warning(message)

    elif level == "error":
        placeholder.error(message)

    else:
        placeholder.info(message)


# =========================================================
# Form header
# =========================================================

page_header_html = (
    '<div class="page-header">'
    '<div class="page-title">'
    '☕ Nawader Newsletter Generator'
    '</div>'
    '<div class="page-caption">'
    'Generate a researched, reviewed, and formatted newsletter article.'
    '</div>'
    '</div>'
)


# =========================================================
# Newsletter form
# =========================================================

with st.form(
    "newsletter_form",
    clear_on_submit=False,
):
    st.markdown(
        page_header_html,
        unsafe_allow_html=True,
    )

    topic = st.text_input(
        "Newsletter topic",
        placeholder=(
            "Example: Specialty coffee quality and standards"
        ),
        label_visibility="collapsed",
    )

    with st.container(
        key="form_actions"
    ):
        button_column, language_column = st.columns(
            [1, 1.2],
            gap="large",
        )

        with button_column:
            submitted = st.form_submit_button(
                "Generate article",
                type="primary",
                use_container_width=True,
            )

        with language_column:
            language = st.radio(
                "Article language / لغة المقال",
                options=[
                    "en",
                    "ar",
                ],
                format_func=lambda value: (
                    "English"
                    if value == "en"
                    else "العربية"
                ),
                horizontal=True,
                key="article_language",
                label_visibility="collapsed",
            )


# =========================================================
# Fixed sidebar placeholders
# =========================================================

with st.sidebar:
    st.markdown(
        "## Workflow details"
    )

    st.markdown(
        "### Workflow status"
    )

    workflow_status_placeholder = st.empty()

    st.markdown(
        "### Writer passes"
    )

    writer_passes_placeholder = st.empty()

    # Export controls will appear here after completion.
    export_placeholder = st.empty()


# =========================================================
# Generate and stream the article
# =========================================================

if submitted:
    cleaned_topic = topic.strip()

    if not cleaned_topic:
        st.warning(
            "Please enter a newsletter topic."
        )
        st.stop()

    # Remove the previous result while the new workflow runs.
    st.session_state.pop(
        "newsletter_result",
        None,
    )

    st.session_state.pop(
        "newsletter_topic",
        None,
    )

    st.session_state.pop(
        "newsletter_language",
        None,
    )

    update_status_display(
        workflow_status_placeholder,
        "Researcher is searching live sources...",
        "info",
    )

    writer_passes_placeholder.metric(
        label="Writer passes",
        value=0,
        label_visibility="collapsed",
    )

    final_result = None

    try:
        with requests.post(
            API_STREAM_URL,
            json={
                "topic": cleaned_topic,
                "language": language,
            },
            stream=True,
            timeout=(
                10,
                600,
            ),
        ) as response:
            response.raise_for_status()
            response.encoding = "utf-8"

            for raw_line in response.iter_lines(
                decode_unicode=True,
                chunk_size=1,
            ):
                if not raw_line:
                    continue

                try:
                    event = json.loads(
                        raw_line
                    )

                except json.JSONDecodeError as error:
                    raise RuntimeError(
                        "The API returned an invalid "
                        "streaming event."
                    ) from error

                event_type = event.get(
                    "type"
                )

                # -----------------------------------------
                # Workflow progress
                # -----------------------------------------

                if event_type == "progress":
                    message = event.get(
                        "message",
                        "Workflow is running...",
                    )

                    level = event.get(
                        "level",
                        "info",
                    )

                    revision_count = int(
                        event.get(
                            "revision_count",
                            0,
                        )
                    )

                    update_status_display(
                        workflow_status_placeholder,
                        message,
                        level,
                    )

                    writer_passes_placeholder.metric(
                        label="Writer passes",
                        value=revision_count,
                        label_visibility="collapsed",
                    )

                # -----------------------------------------
                # Final result
                # -----------------------------------------

                elif event_type == "result":
                    final_result = event.get(
                        "data"
                    )

                # -----------------------------------------
                # Workflow error
                # -----------------------------------------

                elif event_type == "error":
                    raise RuntimeError(
                        event.get(
                            "message",
                            "The workflow failed.",
                        )
                    )

        if not final_result:
            raise RuntimeError(
                "The workflow finished without "
                "returning an article."
            )

        st.session_state[
            "newsletter_result"
        ] = final_result

        st.session_state[
            "newsletter_topic"
        ] = cleaned_topic

        st.session_state[
            "newsletter_language"
        ] = language

    except requests.ConnectionError:
        update_status_display(
            workflow_status_placeholder,
            "Could not connect to the FastAPI server.",
            "error",
        )

        st.stop()

    except requests.Timeout:
        update_status_display(
            workflow_status_placeholder,
            "The newsletter workflow timed out.",
            "error",
        )

        st.stop()

    except requests.HTTPError as error:
        error_message = str(error)

        if error.response is not None:
            try:
                response_data = error.response.json()

                error_message = response_data.get(
                    "detail",
                    error_message,
                )

            except ValueError:
                pass

        update_status_display(
            workflow_status_placeholder,
            error_message,
            "error",
        )

        st.stop()

    except requests.RequestException as error:
        update_status_display(
            workflow_status_placeholder,
            f"Request failed: {error}",
            "error",
        )

        st.stop()

    except RuntimeError as error:
        update_status_display(
            workflow_status_placeholder,
            str(error),
            "error",
        )

        st.stop()


# =========================================================
# Read the completed result from session state
# =========================================================

result = st.session_state.get(
    "newsletter_result"
)

selected_topic = st.session_state.get(
    "newsletter_topic",
    "",
)

selected_language = st.session_state.get(
    "newsletter_language",
    "en",
)


# =========================================================
# Sidebar result and exports
# =========================================================

if result:
    revision_count = int(
        result.get(
            "revision_count",
            0,
        )
    )

    final_status = result.get(
        "final_status",
        "",
    )

    writer_passes_placeholder.metric(
        label="Writer passes",
        value=revision_count,
        label_visibility="collapsed",
    )

    if final_status == "APPROVED":
        update_status_display(
            workflow_status_placeholder,
            "✅ Editor approved. Article ready.",
            "success",
        )

    elif final_status == "REVISION_CAP_REACHED":
        update_status_display(
            workflow_status_placeholder,
            (
                "⚠️ Revision cap reached. "
                "Best available article ready."
            ),
            "warning",
        )

    else:
        update_status_display(
            workflow_status_placeholder,
            "The workflow finished in an unexpected state.",
            "error",
        )

    # Downloads appear only after the article is finished.
    with export_placeholder.container():
        st.divider()

        st.markdown(
            "### Export article"
        )

        export_format = st.radio(
            "Choose a file type",
            options=list(
                EXPORT_FORMATS.keys()
            ),
            format_func=lambda value: (
                EXPORT_FORMATS[value]["label"]
            ),
            key="export_format",
        )

        try:
            (
                export_data,
                export_filename,
                export_mime,
            ) = build_export_file(
                article_markdown=result[
                    "article_markdown"
                ],
                topic=selected_topic,
                language=selected_language,
                export_format=export_format,
            )

            st.download_button(
                label=(
                    "⬇️ Download "
                    f"{EXPORT_FORMATS[export_format]['label']}"
                ),
                data=export_data,
                file_name=export_filename,
                mime=export_mime,
                key="download_article",
                use_container_width=True,
                on_click="ignore",
            )

        except Exception as error:
            st.error(
                f"Could not prepare export: {error}"
            )

else:
    # Initial sidebar state.
    if not submitted:
        workflow_status_placeholder.info(
            "Ready to generate a newsletter."
        )

        writer_passes_placeholder.metric(
            label="Writer passes",
            value=0,
            label_visibility="collapsed",
        )


# =========================================================
# Final article — directly under the form
# =========================================================

if result:
    article_section_title = (
        "المقال النهائي للنشرة"
        if selected_language == "ar"
        else "Final newsletter article"
    )

    st.markdown(
        (
            '<div class="article-section-title">'
            f"{article_section_title}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    article_panel_key = (
        "article_panel_ar"
        if selected_language == "ar"
        else "article_panel_en"
    )

    with st.container(
        key=article_panel_key
    ):
        st.markdown(
            result["article_markdown"]
        )

    research_notes_label = (
        "🔎 عرض ملاحظات البحث"
        if selected_language == "ar"
        else "🔎 View research notes"
    )

    with st.expander(
        research_notes_label
    ):
        research_notes = result.get(
            "research_notes",
            [],
        )

        if research_notes:
            for number, note in enumerate(
                research_notes,
                start=1,
            ):
                st.write(
                    f"{number}. {note}"
                )

        else:
            st.info(
                "No research notes were returned."
            )

    final_critique = result.get(
        "final_critique",
        "",
    )

    if final_critique:
        critique_label = (
            "🧐 عرض المراجعة النهائية للمحرر"
            if selected_language == "ar"
            else "🧐 View final editor critique"
        )

        with st.expander(
            critique_label
        ):
            st.write(
                final_critique
            )