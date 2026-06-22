from pathlib import Path
import logging
import markdown
import weasyprint

logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fonttools").setLevel(logging.ERROR)

_CSS = """
@page {
    margin: 2.5cm;
    size: A4;
    @bottom-center {
        content: counter(page) " z " counter(pages);
        font-family: "DejaVu Sans", Arial, sans-serif;
        font-size: 8.5pt;
        color: #888;
    }
}

body {
    font-family: "DejaVu Serif", Georgia, "Times New Roman", serif;
    font-size: 10.5pt;
    line-height: 1.72;
    color: #1a1a1a;
}

h1 {
    font-family: "DejaVu Sans", Arial, sans-serif;
    font-size: 17pt;
    font-weight: 700;
    color: #1a3a5c;
    border-bottom: 3px solid #1a3a5c;
    padding-bottom: 10px;
    margin: 0 0 28px 0;
}

h2 {
    font-family: "DejaVu Sans", Arial, sans-serif;
    font-size: 12.5pt;
    font-weight: 700;
    color: #1a3a5c;
    border-left: 5px solid #2e6da4;
    padding-left: 12px;
    margin: 32px 0 12px 0;
    page-break-after: avoid;
}

h3 {
    font-family: "DejaVu Sans", Arial, sans-serif;
    font-size: 11pt;
    font-weight: 600;
    color: #2c2c2c;
    margin: 20px 0 8px 0;
    page-break-after: avoid;
}

p {
    margin: 8px 0;
    text-align: justify;
    orphans: 3;
    widows: 3;
}

ul, ol {
    margin: 8px 0;
    padding-left: 22px;
}

li {
    margin: 5px 0;
    line-height: 1.65;
}

strong {
    font-weight: 700;
    color: #14325a;
}

em {
    font-style: italic;
}

hr {
    border: none;
    border-top: 1px solid #bbb;
    margin: 28px 0;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 18px 0;
    font-family: "DejaVu Sans", Arial, sans-serif;
    font-size: 9.5pt;
    page-break-inside: auto;
}

th {
    background-color: #1a3a5c;
    color: #fff;
    font-weight: 600;
    text-align: left;
    padding: 8px 11px;
    border: 1px solid #1a3a5c;
}

td {
    padding: 6px 11px;
    border: 1px solid #ccc;
    vertical-align: top;
    line-height: 1.55;
}

tr:nth-child(even) td {
    background-color: #f2f6fb;
}

tr:nth-child(odd) td {
    background-color: #fff;
}

thead {
    display: table-header-group;
}

code {
    font-family: "DejaVu Sans Mono", "Courier New", monospace;
    font-size: 9pt;
    background-color: #f0f0f0;
    padding: 1px 4px;
    border-radius: 3px;
}

blockquote {
    border-left: 4px solid #2e6da4;
    margin: 12px 0;
    padding: 4px 16px;
    color: #555;
    font-style: italic;
}
"""


def save(source_path: Path, content: str) -> Path:
    md_path = source_path.with_name(source_path.stem + "_raport.md")
    md_path.write_text(content, encoding="utf-8")

    pdf_path = source_path.with_name(source_path.stem + "_raport.pdf")
    _to_pdf(content, pdf_path, title=source_path.stem)
    return pdf_path


def _to_pdf(md_content: str, output: Path, title: str = "") -> None:
    html_body = markdown.markdown(
        md_content,
        extensions=["tables", "sane_lists"],
    )
    display_title = title.replace("_raport", "").replace("_", " ")
    heading = f"<h1>{display_title}</h1>\n" if display_title else ""
    html = (
        "<!DOCTYPE html>"
        "<html lang='pl'>"
        "<head>"
        "<meta charset='UTF-8'>"
        f"<title>{display_title}</title>"
        f"<style>{_CSS}</style>"
        "</head>"
        f"<body>{heading}{html_body}</body>"
        "</html>"
    )
    weasyprint.HTML(string=html).write_pdf(str(output))
