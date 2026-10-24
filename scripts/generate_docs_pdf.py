"""
scripts/generate_docs_pdf.py
High-quality PDF Reference Document Generator for Project 357 (KubePilot).
Uses ReportLab with custom canvas for 'Page X of Y' headers/footers,
clean tables, syntax/code blocks, and executive layout styling.
"""

import os
import sys
import re
import html
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Preformatted,
    KeepTogether,
    HRFlowable,
)
from reportlab.pdfgen import canvas

# Define clean enterprise palette
PRIMARY = colors.HexColor("#0F172A")    # Slate 900
SECONDARY = colors.HexColor("#1E3A8A")  # Blue 900
ACCENT = colors.HexColor("#2563EB")     # Blue 600
TEXT_MAIN = colors.HexColor("#1E293B")  # Slate 800
TEXT_MUTED = colors.HexColor("#64748B") # Slate 500
BG_CODE = colors.HexColor("#F8FAFC")    # Slate 50
BORDER_COLOR = colors.HexColor("#E2E8F0")# Slate 200
HEADER_BG = colors.HexColor("#F1F5F9")  # Slate 100
ALERT_BG = colors.HexColor("#EFF6FF")   # Blue 50
ALERT_BORDER = colors.HexColor("#93C5FD")# Blue 300


class NumberedCanvas(canvas.Canvas):
    """Canvas that computes total pages dynamically and adds running headers & footers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(TEXT_MUTED)

        # Running Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(36, 11 * inch - 30, getattr(self, "doc_title", "Project 357 Reference Guide"))
            self.drawRightString(8.5 * inch - 36, 11 * inch - 30, "KubePilot: Kubernetes Autoscaling")
            self.setStrokeColor(BORDER_COLOR)
            self.setLineWidth(0.5)
            self.line(36, 11 * inch - 34, 8.5 * inch - 36, 11 * inch - 34)

        # Running Footer (all pages)
        self.setStrokeColor(BORDER_COLOR)
        self.setLineWidth(0.5)
        self.line(36, 38, 8.5 * inch - 36, 38)
        self.drawString(36, 26, "Project 357: Kubernetes-Based Auto-Scaling Framework for Cloud Applications")
        self.drawRightString(8.5 * inch - 36, 26, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def create_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="DocTitle",
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=PRIMARY,
        spaceAfter=4,
    ))

    styles.add(ParagraphStyle(
        name="DocSubtitle",
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=TEXT_MUTED,
        spaceAfter=12,
    ))

    styles.add(ParagraphStyle(
        name="SectionH1",
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=SECONDARY,
        spaceBefore=12,
        spaceAfter=5,
        keepWithNext=True,
    ))

    styles.add(ParagraphStyle(
        name="SectionH2",
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=PRIMARY,
        spaceBefore=9,
        spaceAfter=3,
        keepWithNext=True,
    ))

    styles.add(ParagraphStyle(
        name="DocBody",
        fontName="Helvetica",
        fontSize=8.5,
        leading=12.5,
        textColor=TEXT_MAIN,
        spaceAfter=5,
    ))

    styles.add(ParagraphStyle(
        name="DocBullet",
        fontName="Helvetica",
        fontSize=8.5,
        leading=12.5,
        textColor=TEXT_MAIN,
        leftIndent=14,
        firstLineIndent=-10,
        spaceAfter=3,
    ))

    styles.add(ParagraphStyle(
        name="CodeBlock",
        fontName="Courier",
        fontSize=7,
        leading=9.5,
        textColor=colors.HexColor("#0F172A"),
    ))

    styles.add(ParagraphStyle(
        name="TableHeader",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10.5,
        textColor=PRIMARY,
    ))

    styles.add(ParagraphStyle(
        name="TableCell",
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=TEXT_MAIN,
    ))

    styles.add(ParagraphStyle(
        name="AlertText",
        fontName="Helvetica",
        fontSize=8,
        leading=11.5,
        textColor=SECONDARY,
    ))

    return styles


def format_markdown_inline(text):
    """Converts inline markdown formatting (**bold**, `code`, *italic*) to ReportLab HTML tags safely."""
    # 1. Protect code snippets `...`
    code_placeholders = []
    def code_repl(m):
        code_content = m.group(1)
        # Escape HTML entities inside code
        escaped_code = html.escape(code_content)
        idx = len(code_placeholders)
        code_placeholders.append(f'<font face="Courier" color="#0F172A"><b>{escaped_code}</b></font>')
        return f"__CODE_SNIP_{idx}__"

    text = re.sub(r"`([^`]+)`", code_repl, text)

    # 2. Escape XML/HTML entities in remaining text
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 3. Clean KaTeX/math symbols if present
    text = re.sub(r"\$\$(.*?)\$\$", r"<i>\1</i>", text)
    text = re.sub(r"\$(.*?)\$", r"<i>\1</i>", text)

    # 4. Bold **text**
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)

    # 5. Italic *text* (word boundary or spaces to avoid wildcards in filenames)
    text = re.sub(r"(?<!\w)\*([^\*]+?)\*(?!\w)", r"<i>\1</i>", text)

    # 6. Links [label](url) -> label
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"<u>\1</u>", text)

    # 7. Restore code snippets
    for idx, snippet in enumerate(code_placeholders):
        text = text.replace(f"__CODE_SNIP_{idx}__", snippet)

    return text


def render_table(rows, styles):
    if not rows:
        return Spacer(1, 1)

    num_cols = max(len(r) for r in rows)
    norm_rows = []
    for r_idx, r in enumerate(rows):
        cells = []
        is_header = (r_idx == 0)
        style_key = "TableHeader" if is_header else "TableCell"
        for c in r:
            c_html = format_markdown_inline(c)
            cells.append(Paragraph(c_html, styles[style_key]))
        while len(cells) < num_cols:
            cells.append(Paragraph("", styles[style_key]))
        norm_rows.append(cells)

    total_width = 7.5 * inch
    col_width = total_width / num_cols
    col_widths = [col_width] * num_cols

    t = Table(norm_rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
    ]))
    return t


def parse_markdown_to_flowables(md_text, styles, doc_title="Project 357 Reference"):
    flowables = []
    lines = md_text.splitlines()
    i = 0
    n = len(lines)

    in_code = False
    code_lines = []

    in_table = False
    table_rows = []

    while i < n:
        line = lines[i]

        # Handle Code Blocks
        if line.strip().startswith("```"):
            if in_code:
                in_code = False
                # Filter out pure mermaid tags or render them as text
                code_content = "\n".join(code_lines)
                # Trim lines exceeding 95 characters for clean wrapping
                wrapped_lines = []
                for cl in code_lines:
                    if len(cl) > 95:
                        wrapped_lines.append(cl[:95] + "...")
                    else:
                        wrapped_lines.append(cl)
                code_content = "\n".join(wrapped_lines)
                code_p = Preformatted(code_content, styles["CodeBlock"])
                t = Table([[code_p]], colWidths=[7.5 * inch])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), BG_CODE),
                    ('BOX', (0,0), (-1,-1), 0.5, BORDER_COLOR),
                    ('LEFTPADDING', (0,0), (-1,-1), 6),
                    ('RIGHTPADDING', (0,0), (-1,-1), 6),
                    ('TOPPADDING', (0,0), (-1,-1), 4),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ]))
                flowables.append(t)
                flowables.append(Spacer(1, 4))
                code_lines = []
            else:
                in_code = True
                code_lines = []
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        # Handle Markdown Tables
        if "|" in line and line.strip().startswith("|") and line.strip().endswith("|"):
            cells = [c.strip() for c in line.strip().split("|")[1:-1]]
            if all(re.match(r"^:?-+:?$", c) for c in cells):
                i += 1
                continue
            table_rows.append(cells)
            in_table = True
            i += 1
            continue
        elif in_table:
            in_table = False
            if table_rows:
                flowable_table = render_table(table_rows, styles)
                flowables.append(flowable_table)
                flowables.append(Spacer(1, 6))
                table_rows = []

        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Header 1
        if stripped.startswith("# "):
            title_text = stripped[2:].strip()
            flowables.append(Paragraph(html.escape(title_text), styles["DocTitle"]))
            flowables.append(HRFlowable(width="100%", thickness=1.5, color=ACCENT, spaceAfter=6))
            i += 1
            continue

        # Header 2
        if stripped.startswith("## "):
            h2_text = stripped[3:].strip()
            flowables.append(Paragraph(html.escape(h2_text), styles["SectionH1"]))
            flowables.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_COLOR, spaceAfter=4))
            i += 1
            continue

        # Header 3
        if stripped.startswith("### "):
            h3_text = stripped[4:].strip()
            flowables.append(Paragraph(html.escape(h3_text), styles["SectionH2"]))
            i += 1
            continue

        # Blockquote / Alert
        if stripped.startswith("> "):
            alert_text = stripped[2:].strip()
            alert_html = format_markdown_inline(alert_text)
            alert_p = Paragraph(alert_html, styles["AlertText"])
            t = Table([[alert_p]], colWidths=[7.5 * inch])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), ALERT_BG),
                ('BOX', (0,0), (-1,-1), 1, ALERT_BORDER),
                ('LEFTPADDING', (0,0), (-1,-1), 8),
                ('RIGHTPADDING', (0,0), (-1,-1), 8),
                ('TOPPADDING', (0,0), (-1,-1), 5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ]))
            flowables.append(t)
            flowables.append(Spacer(1, 5))
            i += 1
            continue

        # Horizontal rule ---
        if re.match(r"^-{3,}$", stripped) or re.match(r"^\*{3,}$", stripped):
            flowables.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_COLOR, spaceBefore=4, spaceAfter=6))
            i += 1
            continue

        # Unordered Bullet list
        if stripped.startswith("* ") or stripped.startswith("- "):
            bullet_text = stripped[2:].strip()
            bullet_html = format_markdown_inline(bullet_text)
            flowables.append(Paragraph(f"&bull; {bullet_html}", styles["DocBullet"]))
            i += 1
            continue

        # Numbered list
        m = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if m:
            num = m.group(1)
            num_text = m.group(2)
            num_html = format_markdown_inline(num_text)
            flowables.append(Paragraph(f"<b>{num}.</b> {num_html}", styles["DocBullet"]))
            i += 1
            continue

        # Standard paragraph
        body_html = format_markdown_inline(stripped)
        flowables.append(Paragraph(body_html, styles["DocBody"]))
        i += 1

    if in_table and table_rows:
        flowable_table = render_table(table_rows, styles)
        flowables.append(flowable_table)
        flowables.append(Spacer(1, 6))

    return flowables


def build_pdf(output_path, doc_title, md_files):
    styles = create_styles()
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=46,
        bottomMargin=46,
    )

    combined_flowables = []
    combined_flowables.append(Paragraph(f"PROJECT 357 TECHNICAL REFERENCE", styles["DocSubtitle"]))

    for idx, md_file in enumerate(md_files):
        if not os.path.exists(md_file):
            print(f"Warning: file {md_file} not found. Skipping.")
            continue
        with open(md_file, "r", encoding="utf-8") as f:
            md_content = f.read()

        flowables = parse_markdown_to_flowables(md_content, styles, doc_title)
        combined_flowables.extend(flowables)
        if idx < len(md_files) - 1:
            combined_flowables.append(Spacer(1, 12))

    def canvas_maker(*args, **kwargs):
        c = NumberedCanvas(*args, **kwargs)
        c.doc_title = doc_title
        return c

    doc.build(combined_flowables, canvasmaker=canvas_maker)
    print(f"[OK] Generated: {output_path} ({os.path.getsize(output_path):,} bytes)")


def main():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    docs_dir = os.path.join(base_dir, "documents")
    md_dir = os.path.join(docs_dir, "markdown")
    pdf_dir = os.path.join(docs_dir, "pdf")

    os.makedirs(pdf_dir, exist_ok=True)

    tasks = [
        (
            os.path.join(pdf_dir, "PROJECT_REFERENCE.pdf"),
            "Project 357: Project Reference Manual",
            [
                os.path.join(md_dir, "PROJECT_OVERVIEW.md"),
                os.path.join(md_dir, "EXPERIMENTS_AND_EVALUATION.md"),
            ],
        ),
        (
            os.path.join(pdf_dir, "SYSTEM_ARCHITECTURE.pdf"),
            "Project 357: System Architecture Specification",
            [
                os.path.join(md_dir, "SYSTEM_ARCHITECTURE.md"),
                os.path.join(md_dir, "IMPLEMENTATION_DETAILS.md"),
            ],
        ),
        (
            os.path.join(pdf_dir, "SETUP_AND_EXECUTION.pdf"),
            "Project 357: Setup and Execution Guide",
            [
                os.path.join(md_dir, "SETUP_AND_EXECUTION.md"),
                os.path.join(md_dir, "TROUBLESHOOTING.md"),
            ],
        ),
        (
            os.path.join(pdf_dir, "TESTING_AND_VERIFICATION.pdf"),
            "Project 357: Testing & Verification Report",
            [
                os.path.join(md_dir, "TESTING_AND_VERIFICATION.md"),
                os.path.join(md_dir, "API_REFERENCE.md"),
            ],
        ),
    ]

    for output_pdf, title, md_files in tasks:
        build_pdf(output_pdf, title, md_files)

    print("\nAll 4 reference PDFs successfully generated under documents/pdf/.")


if __name__ == "__main__":
    main()
