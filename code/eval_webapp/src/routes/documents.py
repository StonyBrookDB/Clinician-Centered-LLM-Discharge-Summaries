"""Documents viewer route for displaying discharge summaries."""

import json
import html
from fastapi import APIRouter, Request, Depends, Query, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response, HTMLResponse
from pathlib import Path

from eval_v2.config import (
    TEMPLATES_DIR,
    is_gating_logic_enabled,
    is_highlights_enabled,
    is_first_look_enabled,
)
from eval_v2.auth.manager import manager
from eval_v2.services.db_connection import get_connection
from eval_v2.services.notes_loader import load_encounter_documents
from eval_v2.services import file_encryption
from eval_v2.services.doctor_lookup import get_doctor_id_for_user
from eval_v2.routes.incidental_findings import get_incidental_findings
from eval_v2.routes.ratings import get_review_data
from eval_v2.services.review_completion import recompute_and_persist
from eval_v2.services.example_case import is_example_read_only
from eval_v2.services.admin_access import is_admin_user
from eval_v2.services.dummy_account import DUMMY_ENCOUNTER_NUMBER, DUMMY_EMAIL
from eval_v2.services.markdown_renderer import (
    get_or_create_markdown,
    render_markdown_to_html,
    is_markdown_failed,
    is_html_render_failed,
    mark_html_render_failed,
    clear_html_render_failed,
)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _require_assigned_encounter(
    encounter_number: int,
    user: dict,
    *,
    review_doctor_id: int | None = None,
) -> int:
    """Ensure the authenticated user (or admin override) is assigned to the encounter."""
    doctor_id = get_doctor_id_for_user(user)
    if review_doctor_id is not None:
        if not is_admin_user(user):
            raise HTTPException(status_code=403, detail="Admin access required")
        doctor_id = review_doctor_id
    if not doctor_id:
        raise HTTPException(status_code=401, detail="Doctor not found for user")
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 1
            FROM reviews_to_complete
            WHERE encounter_number = ? AND doctor_id = ?
            """,
            (encounter_number, doctor_id),
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=403, detail="Encounter not assigned to this reviewer")
    return doctor_id


def _find_clinical_note(docs, filename: str):
    safe_name = Path(filename).name
    base_name = safe_name
    for suffix in (".rtf", ".pdf", ".html", ".md"):
        if base_name.endswith(suffix):
            base_name = base_name[: -len(suffix)]
            break

    for note in docs.clinical_notes:
        note_base = Path(note.file_name).stem
        if note.file_name == safe_name or note_base == base_name:
            return note
    return None


def get_first_look(encounter_number: int, doctor_id: int) -> str:
    """Get the first_look value for an encounter/doctor pair."""
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT first_look FROM reviews_to_complete WHERE encounter_number = ? AND doctor_id = ?",
            (encounter_number, doctor_id),
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] else "Human"


def _get_doctor_label(doctor_id: int) -> dict | None:
    with get_connection(read_only=True) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT first_name, last_name, email
            FROM doctors
            WHERE id = ?
            """,
            (doctor_id,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    first_name = row[0] or ""
    last_name = row[1] or ""
    email = row[2] or ""
    label = f"{first_name} {last_name}".strip() or email or f"Doctor {doctor_id}"
    return {"first_name": first_name, "last_name": last_name, "email": email, "label": label}


@router.get("/documents")
async def documents(
    request: Request,
    encounter_number: int = Query(...),
    review_doctor_id: int | None = Query(None),
    admin_view: bool = Query(False),
    user: dict = Depends(manager),
):
    """Display the document viewer for a specific encounter."""
    error = None
    encounter_docs = None
    clinical_notes_data = []
    summary_a_parts = []
    summary_b_text = None
    first_look = "Human"
    enable_highlights = is_highlights_enabled()
    enable_first_look = is_first_look_enabled()
    review = None
    viewer_doctor_id = get_doctor_id_for_user(user)
    is_admin = is_admin_user(user)
    read_only_admin = bool(admin_view and is_admin and review_doctor_id is not None)
    effective_doctor_id = viewer_doctor_id
    review_owner = None
    incidental_findings = []
    read_only_example = is_example_read_only(encounter_number)
    is_dummy_user = (user.get("email") or "").strip().lower() == DUMMY_EMAIL
    show_dummy_banner = is_dummy_user or encounter_number == DUMMY_ENCOUNTER_NUMBER

    try:
        if review_doctor_id is not None:
            if not admin_view or not is_admin:
                raise HTTPException(status_code=403, detail="Admin review access denied")
            effective_doctor_id = review_doctor_id

        if not effective_doctor_id:
            raise ValueError("No doctor record found for current user.")

        if not read_only_example and not read_only_admin:
            recompute_and_persist(encounter_number, effective_doctor_id)
        review = get_review_data(encounter_number, effective_doctor_id)
        if not review:
            raise ValueError(f"No review assignment found for encounter {encounter_number}.")

        encounter_docs = load_encounter_documents(encounter_number)
        if enable_first_look:
            first_look = review.get("first_look") or get_first_look(encounter_number, effective_doctor_id)
        else:
            first_look = "Human"
        incidental_findings = get_incidental_findings(encounter_number, effective_doctor_id)
        if review_doctor_id is not None:
            review_owner = _get_doctor_label(effective_doctor_id)

        # Build clinical notes data for template
        for note in encounter_docs.clinical_notes:
            md_path = note.path.with_suffix(".md")
            html_failed = is_markdown_failed(md_path) or is_html_render_failed(md_path)
            clinical_notes_data.append({
                "position": note.position,
                "display_name": note.display_name,
                "file_name": note.file_name,
                "has_html": note.has_html and not html_failed,
                "has_pdf": note.has_pdf,
                "html_failed": html_failed,
                "cited_by_ai": note.cited_by_ai,
                "relative_day": note.relative_day,
                "note_type": note.note_type,
                "publish_ts_raw": note.publish_ts_raw,
            })

        # Build Summary A parts
        has_inpatient_rtf = encounter_docs.inpatient_summary_rtf and encounter_docs.inpatient_summary_rtf.exists()
        has_inpatient_pdf = encounter_docs.inpatient_summary_pdf and encounter_docs.inpatient_summary_pdf.exists()
        if has_inpatient_rtf or has_inpatient_pdf:
            inpatient_md = None
            inpatient_html_failed = False
            if has_inpatient_rtf:
                inpatient_md = encounter_docs.inpatient_summary_rtf.with_suffix(".md")
                inpatient_html_failed = is_markdown_failed(inpatient_md) or is_html_render_failed(inpatient_md)
            summary_a_parts.append({
                "label": "Part 1",
                "filename": "inpatient_summary",
                "url_slug": "inpatient_summary",
                "available": True,
                "has_html": has_inpatient_rtf and not inpatient_html_failed,
                "has_pdf": has_inpatient_pdf,
                "html_failed": inpatient_html_failed,
            })
        else:
            summary_a_parts.append({
                "label": "Part 1",
                "filename": "inpatient_summary",
                "available": False,
                "has_html": False,
                "has_pdf": False,
                "error": "Inpatient clinical summary not found.",
            })

        has_human_rtf = encounter_docs.human_summary_rtf and encounter_docs.human_summary_rtf.exists()
        has_human_pdf = encounter_docs.human_summary_pdf and encounter_docs.human_summary_pdf.exists()
        if has_human_rtf or has_human_pdf:
            human_md = None
            human_html_failed = False
            if has_human_rtf:
                human_md = encounter_docs.human_summary_rtf.with_suffix(".md")
                human_html_failed = is_markdown_failed(human_md) or is_html_render_failed(human_md)
            summary_a_parts.append({
                "label": "Part 2",
                "filename": "human_summary",
                "url_slug": "summary_a_part2",
                "available": True,
                "has_html": has_human_rtf and not human_html_failed,
                "has_pdf": has_human_pdf,
                "html_failed": human_html_failed,
            })
        else:
            summary_a_parts.append({
                "label": "Part 2",
                "filename": "human_summary",
                "available": False,
                "has_html": False,
                "has_pdf": False,
                "error": "Discharge Summary A not found.",
            })

        # Load Summary B text
        if encounter_docs.ai_summary_txt and encounter_docs.ai_summary_txt.exists():
            try:
                summary_b_text = file_encryption.get_bytes(encounter_docs.ai_summary_txt).decode("utf-8", errors="ignore")
            except Exception:
                summary_b_text = "[Error loading AI summary text]"

    except FileNotFoundError as e:
        error = f"Encounter documents not found: {e}"
    except Exception as e:
        error = f"Error loading documents: {e}"

    summary_tabs = ["summary_b", "summary_a"] if (enable_first_look and first_look == "AI") else ["summary_a", "summary_b"]
    tab_order = (
        ["clinical_notes"]
        + (["highlights_timeline"] if enable_highlights else [])
        + summary_tabs
        + ["incidental_findings", "overall_preference"]
    )

    default_tab = "clinical_notes"

    return templates.TemplateResponse(
        "documents.html",
        {
            "request": request,
            "user": user,
            "encounter_number": encounter_number,
            "doctor_id": effective_doctor_id or 0,
            "review_doctor_id": effective_doctor_id or 0,
            "patient_age": review.get("patient_age") if review else None,
            "patient_gender": review.get("patient_gender") if review else None,
            "los": review.get("los") if review else None,
            "error": error,
            "clinical_notes": clinical_notes_data,
            "summary_a_parts": summary_a_parts,
            "summary_b_text": summary_b_text,
            "first_look": first_look,
            "tab_order": tab_order,
            "default_tab": default_tab,
            "review": review,
            "incidental_findings": incidental_findings,
            "read_only_example": read_only_example,
            "read_only_admin": read_only_admin,
            "review_owner": review_owner,
            "show_dummy_banner": show_dummy_banner,
            "enable_gating_logic": is_gating_logic_enabled(),
            "enable_highlights": enable_highlights,
            "enable_first_look": enable_first_look,
        },
    )


# --- PDF Serving Endpoints ---

@router.get("/pdf/{encounter_number}/inpatient_summary")
async def serve_inpatient_summary(
    encounter_number: int,
    review_doctor_id: int | None = Query(None),
    admin_view: bool = Query(False),
    user: dict = Depends(manager),
):
    """Serve the inpatient clinical summary PDF (Summary A Part 1)."""
    try:
        _require_assigned_encounter(
            encounter_number,
            user,
            review_doctor_id=review_doctor_id if admin_view else None,
        )
        docs = load_encounter_documents(encounter_number)
        if not docs.inpatient_summary_pdf or not docs.inpatient_summary_pdf.exists():
            raise HTTPException(status_code=404, detail="Inpatient summary PDF not found")

        pdf_bytes = file_encryption.get_bytes(docs.inpatient_summary_pdf)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "inline; filename=inpatient_clinical_summary.pdf"},
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Encounter not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pdf/{encounter_number}/human_summary")
@router.get("/pdf/{encounter_number}/summary_a_part2")
async def serve_human_summary(
    encounter_number: int,
    review_doctor_id: int | None = Query(None),
    admin_view: bool = Query(False),
    user: dict = Depends(manager),
):
    """Serve Summary A Part 2 PDF."""
    try:
        _require_assigned_encounter(
            encounter_number,
            user,
            review_doctor_id=review_doctor_id if admin_view else None,
        )
        docs = load_encounter_documents(encounter_number)
        if not docs.human_summary_pdf or not docs.human_summary_pdf.exists():
            raise HTTPException(status_code=404, detail="Summary A Part 2 PDF not found")

        pdf_bytes = file_encryption.get_bytes(docs.human_summary_pdf)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "inline; filename=summary_A.pdf"},
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Encounter not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pdf/{encounter_number}/clinical_note/{filename:path}")
async def serve_clinical_note_pdf(
    encounter_number: int,
    filename: str,
    review_doctor_id: int | None = Query(None),
    admin_view: bool = Query(False),
    user: dict = Depends(manager),
):
    """Serve a clinical note as PDF."""
    try:
        _require_assigned_encounter(
            encounter_number,
            user,
            review_doctor_id=review_doctor_id if admin_view else None,
        )
        docs = load_encounter_documents(encounter_number)
        target_note = _find_clinical_note(docs, filename)
        if not target_note:
            raise HTTPException(status_code=404, detail=f"Clinical note not found: {filename}")

        pdf_path = target_note.pdf_path
        if not pdf_path or not pdf_path.exists():
            raise HTTPException(status_code=404, detail=f"Clinical note PDF not found: {filename}")

        pdf_bytes = file_encryption.get_bytes(pdf_path)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename={pdf_path.name}"},
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Encounter not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def wrap_html_content(html_body: str, content_id: str = "document-content", encounter_number: int = 0) -> str:
    """Wrap HTML content in a full document with styling for display and highlighting."""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    color: #1f2937;
    padding: 1rem;
    margin: 0;
}}
.document-content {{
    word-wrap: break-word;
}}
.document-content p {{
    margin: 0.5em 0;
}}
.document-content table {{
    border-collapse: collapse;
    margin: 1em 0;
}}
.document-content td, .document-content th {{
    border: 1px solid #e5e7eb;
    padding: 0.5em;
}}
/* Highlight styles */
.user-highlight {{
    cursor: pointer;
    border-radius: 2px;
}}
.user-highlight:hover {{
    filter: brightness(0.95);
}}
.user-highlight.yellow {{ background-color: #fef08a; }}
.user-highlight.green {{ background-color: #bbf7d0; }}
.user-highlight.blue {{ background-color: #bfdbfe; }}
.user-highlight.pink {{ background-color: #fbcfe8; }}
.user-highlight.orange {{ background-color: #fed7aa; }}
</style>
</head>
<body>
<div class="document-content" id="{content_id}" data-encounter="{encounter_number}">{html_body}</div>
</body>
</html>"""


def _render_html_fallback(message: str, payload: dict) -> HTMLResponse:
    safe_message = html.escape(message)
    payload_json = json.dumps(payload)
    html_body = f"""
<div class="render-fallback">
  <strong>HTML view unavailable.</strong>
  <p>{safe_message}</p>
  <p>Switching to PDF view.</p>
</div>
<script>
(function() {{
  const payload = {payload_json};
  if (window.parent && window.parent !== window) {{
    if (typeof window.parent.handleHtmlRenderFailure === 'function') {{
      window.parent.handleHtmlRenderFailure(payload);
    }} else {{
      window.parent.postMessage({{ type: 'html_render_failed', payload }}, window.location.origin);
    }}
  }}
}})();
</script>
"""
    html_content = wrap_html_content(html_body, content_id="render-fallback", encounter_number=payload.get("encounter_number", 0))
    return HTMLResponse(content=html_content)


@router.get("/html/{encounter_number}/clinical_note/{filename:path}")
async def serve_clinical_note_html(
    encounter_number: int,
    filename: str,
    review_doctor_id: int | None = Query(None),
    admin_view: bool = Query(False),
    user: dict = Depends(manager),
):
    """Serve a clinical note as HTML (Markdown converted and rendered)."""
    try:
        _require_assigned_encounter(
            encounter_number,
            user,
            review_doctor_id=review_doctor_id if admin_view else None,
        )
        docs = load_encounter_documents(encounter_number)

        # Find the matching note
        target_note = _find_clinical_note(docs, filename)

        if not target_note:
            raise HTTPException(status_code=404, detail=f"Clinical note not found: {filename}")

        # Get or create markdown file (stored alongside RTF)
        rtf_path = target_note.path
        md_path = rtf_path.with_suffix(".md")

        if is_markdown_failed(md_path) or is_html_render_failed(md_path):
            message = f"{target_note.display_name} cannot be rendered to HTML."
            return _render_html_fallback(
                message,
                {
                    "type": "clinical_note",
                    "encounter_number": encounter_number,
                    "file_name": target_note.file_name,
                },
            )

        markdown_text = get_or_create_markdown(rtf_path, md_path, encrypted=True)

        if not markdown_text:
            message = f"{target_note.display_name} cannot be rendered to HTML."
            return _render_html_fallback(
                message,
                {
                    "type": "clinical_note",
                    "encounter_number": encounter_number,
                    "file_name": target_note.file_name,
                },
            )

        # Render markdown to HTML
        html_body = render_markdown_to_html(markdown_text)
        if not html_body:
            mark_html_render_failed(md_path, "render_failed")
            message = f"{target_note.display_name} cannot be rendered to HTML."
            return _render_html_fallback(
                message,
                {
                    "type": "clinical_note",
                    "encounter_number": encounter_number,
                    "file_name": target_note.file_name,
                },
            )
        clear_html_render_failed(md_path)

        html_content = wrap_html_content(
            html_body,
            content_id="clinical-note-content",
            encounter_number=encounter_number
        )

        return HTMLResponse(content=html_content)

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Encounter not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/html/{encounter_number}/inpatient_summary")
async def serve_inpatient_summary_html(
    encounter_number: int,
    review_doctor_id: int | None = Query(None),
    admin_view: bool = Query(False),
    user: dict = Depends(manager),
):
    """Serve the inpatient clinical summary as HTML (Summary A Part 1)."""
    try:
        _require_assigned_encounter(
            encounter_number,
            user,
            review_doctor_id=review_doctor_id if admin_view else None,
        )
        docs = load_encounter_documents(encounter_number)
        if not docs.inpatient_summary_rtf or not docs.inpatient_summary_rtf.exists():
            raise HTTPException(status_code=404, detail="Inpatient summary RTF not found")

        # Get or create markdown file
        rtf_path = docs.inpatient_summary_rtf
        md_path = rtf_path.with_suffix(".md")

        if is_markdown_failed(md_path) or is_html_render_failed(md_path):
            message = "Summary A Part 1 cannot be rendered to HTML."
            return _render_html_fallback(
                message,
                {
                    "type": "summary_a",
                    "encounter_number": encounter_number,
                    "part": "inpatient_summary",
                },
            )

        markdown_text = get_or_create_markdown(rtf_path, md_path, encrypted=True)

        if not markdown_text:
            message = "Summary A Part 1 cannot be rendered to HTML."
            return _render_html_fallback(
                message,
                {
                    "type": "summary_a",
                    "encounter_number": encounter_number,
                    "part": "inpatient_summary",
                },
            )

        # Render markdown to HTML
        html_body = render_markdown_to_html(markdown_text)
        if not html_body:
            mark_html_render_failed(md_path, "render_failed")
            message = "Summary A Part 1 cannot be rendered to HTML."
            return _render_html_fallback(
                message,
                {
                    "type": "summary_a",
                    "encounter_number": encounter_number,
                    "part": "inpatient_summary",
                },
            )
        clear_html_render_failed(md_path)

        html_content = wrap_html_content(
            html_body,
            content_id="inpatient-summary-content",
            encounter_number=encounter_number
        )

        return HTMLResponse(content=html_content)

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Encounter not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/html/{encounter_number}/human_summary")
@router.get("/html/{encounter_number}/summary_a_part2")
async def serve_human_summary_html(
    encounter_number: int,
    review_doctor_id: int | None = Query(None),
    admin_view: bool = Query(False),
    user: dict = Depends(manager),
):
    """Serve Summary A Part 2 as HTML."""
    try:
        _require_assigned_encounter(
            encounter_number,
            user,
            review_doctor_id=review_doctor_id if admin_view else None,
        )
        docs = load_encounter_documents(encounter_number)
        if not docs.human_summary_rtf or not docs.human_summary_rtf.exists():
            raise HTTPException(status_code=404, detail="Summary A Part 2 RTF not found")

        # Get or create markdown file
        rtf_path = docs.human_summary_rtf
        md_path = rtf_path.with_suffix(".md")

        if is_markdown_failed(md_path) or is_html_render_failed(md_path):
            message = "Summary A Part 2 cannot be rendered to HTML."
            return _render_html_fallback(
                message,
                {
                    "type": "summary_a",
                    "encounter_number": encounter_number,
                    "part": "human_summary",
                },
            )

        markdown_text = get_or_create_markdown(rtf_path, md_path, encrypted=True)

        if not markdown_text:
            message = "Summary A Part 2 cannot be rendered to HTML."
            return _render_html_fallback(
                message,
                {
                    "type": "summary_a",
                    "encounter_number": encounter_number,
                    "part": "human_summary",
                },
            )

        # Render markdown to HTML
        html_body = render_markdown_to_html(markdown_text)
        if not html_body:
            mark_html_render_failed(md_path, "render_failed")
            message = "Summary A Part 2 cannot be rendered to HTML."
            return _render_html_fallback(
                message,
                {
                    "type": "summary_a",
                    "encounter_number": encounter_number,
                    "part": "human_summary",
                },
            )
        clear_html_render_failed(md_path)

        html_content = wrap_html_content(
            html_body,
            content_id="human-summary-content",
            encounter_number=encounter_number
        )

        return HTMLResponse(content=html_content)

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Encounter not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/html/{encounter_number}/summary_b")
async def serve_summary_b_html(
    encounter_number: int,
    review_doctor_id: int | None = Query(None),
    admin_view: bool = Query(False),
    user: dict = Depends(manager),
):
    """Serve Summary B as styled HTML for inline viewing with annotation support."""
    try:
        _require_assigned_encounter(
            encounter_number,
            user,
            review_doctor_id=review_doctor_id if admin_view else None,
        )
        docs = load_encounter_documents(encounter_number)

        if not docs.ai_summary_txt or not docs.ai_summary_txt.exists():
            raise HTTPException(status_code=404, detail="Summary B not found")

        summary_text = file_encryption.get_bytes(docs.ai_summary_txt).decode("utf-8", errors="ignore")
        summary_text = html.escape(summary_text)

        # Wrap in HTML template for consistent styling and annotation support
        html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.7;
    color: #1f2937;
    padding: 1.5rem;
    max-width: 100%;
    margin: 0;
}}
.summary-content {{
    white-space: pre-wrap;
    word-wrap: break-word;
}}
/* Highlight styles for annotations */
.highlight {{
    background-color: #fef08a;
    cursor: pointer;
}}
.highlight.fabrication {{
    background-color: #fecaca;
}}
.highlight.omission {{
    background-color: #bfdbfe;
}}
.highlight:hover {{
    filter: brightness(0.95);
}}
</style>
</head>
<body>
<div class="summary-content" id="summary-b-content" data-encounter="{encounter_number}">{summary_text}</div>
</body>
</html>"""

        return HTMLResponse(content=html_content)

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Encounter not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
