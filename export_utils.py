import html
import os
import re
from pathlib import Path

import markdown
from bs4 import BeautifulSoup
from fpdf import FPDF


EXPORT_FORMATS = {
    "markdown": {
        "label": "Markdown",
        "extension": "md",
        "mime": "text/markdown",
    },
    "html": {
        "label": "HTML email",
        "extension": "html",
        "mime": "text/html",
    },
    "pdf": {
        "label": "PDF",
        "extension": "pdf",
        "mime": "application/pdf",
    },
    "text": {
        "label": "Plain text",
        "extension": "txt",
        "mime": "text/plain",
    },
}


def create_safe_filename(
    topic: str,
) -> str:
    """
    Convert the newsletter topic into a safe file name.
    """

    cleaned_name = re.sub(
        r"[^\w\-]+",
        "-",
        topic.strip().lower(),
        flags=re.UNICODE,
    )

    cleaned_name = cleaned_name.strip("-_")

    if not cleaned_name:
        return "nawader-newsletter"

    return cleaned_name[:80]


def markdown_to_html_body(
    article_markdown: str,
) -> str:
    """
    Convert Markdown into HTML while escaping any raw HTML
    returned by the model.
    """

    safe_markdown = html.escape(
        article_markdown,
        quote=False,
    )

    return markdown.markdown(
        safe_markdown,
        extensions=[
            "extra",
            "sane_lists",
        ],
        output_format="html",
    )


def build_html_email(
    article_markdown: str,
    title: str,
    language: str,
) -> str:
    """
    Create a complete HTML email document.
    """

    direction = (
        "rtl"
        if language == "ar"
        else "ltr"
    )

    alignment = (
        "right"
        if language == "ar"
        else "left"
    )

    language_code = (
        "ar"
        if language == "ar"
        else "en"
    )

    article_body = markdown_to_html_body(
        article_markdown
    )

    safe_title = html.escape(title)

    return f"""<!DOCTYPE html>
<html lang="{language_code}" dir="{direction}">
<head>
    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >

    <title>{safe_title}</title>

    <style>
        body {{
            margin: 0;
            padding: 32px 16px;
            background: #fff8ef;
            color: #3c2415;
            font-family:
                Arial,
                Tahoma,
                sans-serif;
            direction: {direction};
            text-align: {alignment};
        }}

        .email-wrapper {{
            width: 100%;
            max-width: 680px;
            margin: 0 auto;
        }}

        .email-card {{
            padding: 32px 36px;
            border: 1px solid #d7b995;
            border-radius: 18px;
            background: #ffffff;
        }}

        h1 {{
            margin-top: 0;
            color: #3c2415;
            font-size: 30px;
            line-height: 1.35;
        }}

        h2 {{
            margin-top: 28px;
            color: #6f4e37;
            font-size: 22px;
            line-height: 1.4;
        }}

        h3 {{
            color: #6f4e37;
        }}

        p,
        li {{
            color: #3c2415;
            font-size: 16px;
            line-height: 1.8;
        }}

        ul,
        ol {{
            padding-inline-start: 24px;
        }}

        .email-footer {{
            margin-top: 22px;
            color: #9a765f;
            text-align: center;
            font-size: 12px;
        }}
    </style>
</head>

<body>
    <div class="email-wrapper">
        <article class="email-card">
            {article_body}
        </article>

        <div class="email-footer">
            Nawader Coffee Newsletter
        </div>
    </div>
</body>
</html>
"""


def build_plain_text(
    article_markdown: str,
) -> str:
    """
    Convert Markdown into clean plain text.
    """

    article_html = markdown_to_html_body(
        article_markdown
    )

    soup = BeautifulSoup(
        article_html,
        "html.parser",
    )

    raw_text = soup.get_text(
        separator="\n"
    )

    cleaned_lines: list[str] = []

    for line in raw_text.splitlines():
        cleaned_line = line.strip()

        if cleaned_line:
            cleaned_lines.append(
                cleaned_line
            )

    return "\n\n".join(
        cleaned_lines
    )


def find_unicode_font_pair() -> tuple[Path, Path]:
    """
    Find a system Unicode font for English and Arabic PDF output.

    The font files are read from the operating system and are not
    copied into the project.
    """

    windows_directory = Path(
        os.environ.get(
            "WINDIR",
            r"C:\Windows",
        )
    )

    candidates = [
        (
            windows_directory
            / "Fonts"
            / "arial.ttf",
            windows_directory
            / "Fonts"
            / "arialbd.ttf",
        ),
        (
            Path(
                "/usr/share/fonts/truetype/"
                "dejavu/DejaVuSans.ttf"
            ),
            Path(
                "/usr/share/fonts/truetype/"
                "dejavu/DejaVuSans-Bold.ttf"
            ),
        ),
        (
            Path(
                "/System/Library/Fonts/"
                "Supplemental/Arial.ttf"
            ),
            Path(
                "/System/Library/Fonts/"
                "Supplemental/Arial Bold.ttf"
            ),
        ),
    ]

    for regular_font, bold_font in candidates:
        if regular_font.exists():
            if not bold_font.exists():
                bold_font = regular_font

            return regular_font, bold_font

    raise RuntimeError(
        "PDF export requires a Unicode font. "
        "Install Arial or DejaVu Sans on the system."
    )


def remove_inline_markdown(
    text: str,
) -> str:
    """
    Remove simple inline Markdown markers for PDF rendering.
    """

    text = re.sub(
        r"!\[([^\]]*)\]\([^)]+\)",
        r"\1",
        text,
    )

    text = re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        text,
    )

    text = re.sub(
        r"(\*\*|__)(.*?)\1",
        r"\2",
        text,
    )

    text = re.sub(
        r"(\*|_)(.*?)\1",
        r"\2",
        text,
    )

    text = text.replace(
        "`",
        "",
    )

    return text.strip()


def parse_markdown_blocks(
    article_markdown: str,
) -> list[tuple[str, str]]:
    """
    Convert basic Markdown into PDF-friendly blocks.
    """

    blocks: list[tuple[str, str]] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return

        paragraph = " ".join(
            paragraph_lines
        )

        blocks.append(
            (
                "paragraph",
                remove_inline_markdown(
                    paragraph
                ),
            )
        )

        paragraph_lines.clear()

    for raw_line in article_markdown.splitlines():
        line = raw_line.strip()

        if not line:
            flush_paragraph()
            blocks.append(
                (
                    "space",
                    "",
                )
            )
            continue

        if line.startswith("### "):
            flush_paragraph()
            blocks.append(
                (
                    "heading3",
                    remove_inline_markdown(
                        line[4:]
                    ),
                )
            )
            continue

        if line.startswith("## "):
            flush_paragraph()
            blocks.append(
                (
                    "heading2",
                    remove_inline_markdown(
                        line[3:]
                    ),
                )
            )
            continue

        if line.startswith("# "):
            flush_paragraph()
            blocks.append(
                (
                    "heading1",
                    remove_inline_markdown(
                        line[2:]
                    ),
                )
            )
            continue

        if line.startswith(("- ", "* ")):
            flush_paragraph()
            blocks.append(
                (
                    "bullet",
                    remove_inline_markdown(
                        line[2:]
                    ),
                )
            )
            continue

        numbered_item = re.match(
            r"^\d+\.\s+(.+)$",
            line,
        )

        if numbered_item:
            flush_paragraph()
            blocks.append(
                (
                    "bullet",
                    remove_inline_markdown(
                        numbered_item.group(1)
                    ),
                )
            )
            continue

        if line in {
            "---",
            "***",
            "___",
        }:
            flush_paragraph()
            continue

        paragraph_lines.append(line)

    flush_paragraph()

    return blocks


def build_pdf(
    article_markdown: str,
    title: str,
    language: str,
) -> bytes:
    """
    Create PDF bytes with Arabic RTL and English LTR support.
    """

    regular_font, bold_font = (
        find_unicode_font_pair()
    )

    direction = (
        "rtl"
        if language == "ar"
        else "ltr"
    )

    alignment = (
        "R"
        if language == "ar"
        else "L"
    )

    script = (
        "arab"
        if language == "ar"
        else "latn"
    )

    language_code = (
        "ara"
        if language == "ar"
        else "eng"
    )

    if not re.search(
        r"(?m)^#\s+",
        article_markdown,
    ):
        article_markdown = (
            f"# {title}\n\n"
            f"{article_markdown}"
        )

    pdf = FPDF(
        orientation="P",
        unit="mm",
        format="A4",
    )

    pdf.set_margins(
        left=18,
        top=18,
        right=18,
    )

    pdf.set_auto_page_break(
        auto=True,
        margin=18,
    )

    pdf.add_page()

    pdf.add_font(
        family="Newsletter",
        style="",
        fname=str(regular_font),
    )

    pdf.add_font(
        family="Newsletter",
        style="B",
        fname=str(bold_font),
    )

    pdf.set_text_shaping(
        use_shaping_engine=True,
        direction=direction,
        script=script,
        language=language_code,
    )

    pdf.set_title(title)
    pdf.set_author("Nawader Coffee")

    for block_type, block_text in parse_markdown_blocks(
        article_markdown
    ):
        if block_type == "space":
            pdf.ln(3)
            continue

        if block_type == "heading1":
            pdf.set_font(
                "Newsletter",
                style="B",
                size=20,
            )

            pdf.set_text_color(
                60,
                36,
                21,
            )

            pdf.multi_cell(
                w=0,
                h=10,
                text=block_text,
                align=alignment,
            )

            pdf.ln(3)
            continue

        if block_type == "heading2":
            pdf.set_font(
                "Newsletter",
                style="B",
                size=15,
            )

            pdf.set_text_color(
                111,
                78,
                55,
            )

            pdf.multi_cell(
                w=0,
                h=8,
                text=block_text,
                align=alignment,
            )

            pdf.ln(2)
            continue

        if block_type == "heading3":
            pdf.set_font(
                "Newsletter",
                style="B",
                size=12,
            )

            pdf.set_text_color(
                111,
                78,
                55,
            )

            pdf.multi_cell(
                w=0,
                h=7,
                text=block_text,
                align=alignment,
            )

            pdf.ln(1)
            continue

        pdf.set_font(
            "Newsletter",
            style="",
            size=11,
        )

        pdf.set_text_color(
            60,
            36,
            21,
        )

        if block_type == "bullet":
            block_text = f"• {block_text}"

        pdf.multi_cell(
            w=0,
            h=7,
            text=block_text,
            align=alignment,
        )

        pdf.ln(1.5)

    return bytes(
        pdf.output()
    )


def prepare_export(
    article_markdown: str,
    topic: str,
    language: str,
    export_format: str,
) -> tuple[bytes, str, str]:
    """
    Prepare the selected export file.
    """

    if export_format not in EXPORT_FORMATS:
        raise ValueError(
            f"Unsupported export format: {export_format}"
        )

    export_settings = EXPORT_FORMATS[
        export_format
    ]

    safe_filename = create_safe_filename(
        topic
    )

    filename = (
        f"{safe_filename}."
        f"{export_settings['extension']}"
    )

    mime_type = export_settings["mime"]

    if export_format == "markdown":
        file_data = article_markdown.encode(
            "utf-8-sig"
        )

    elif export_format == "html":
        file_data = build_html_email(
            article_markdown=article_markdown,
            title=topic,
            language=language,
        ).encode("utf-8")

    elif export_format == "pdf":
        file_data = build_pdf(
            article_markdown=article_markdown,
            title=topic,
            language=language,
        )

    else:
        file_data = build_plain_text(
            article_markdown
        ).encode("utf-8-sig")

    return (
        file_data,
        filename,
        mime_type,
    )