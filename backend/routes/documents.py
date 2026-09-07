"""Services-directory and documents endpoints.

These routes receive the request, ask the database helpers for data, and hand
off file serving to a short-lived signed link (see utils.helpers).
"""
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from urllib.parse import quote

from auth.dependencies import get_authenticated_user, require_admin
from config import ALLOWED_STORAGE_ROOTS, STORAGE_DIR
from database.connection import get_db
from database.models import Document, Service
from rag.ingestion import deindex_document, index_document, is_indexed, normalize_status
from sqlalchemy import select
from utils.helpers import sign_file_link, verify_file_link

router = APIRouter()


# Returns the company services directory.
# Takes: none.
# Returns: a dict whose "services" value is the list of service entries.
@router.get("/api/services")
def list_services(_=Depends(get_authenticated_user), db=Depends(get_db)):
    services = db.scalars(select(Service)).all()

    result = []

    for service in services:
        entry = service_dict(service)
        result.append(entry)

    return {"services": result}


# Returns the document registry, optionally filtered by category.
# Takes: category - an optional category to filter by.
# Returns: a dict whose "documents" value is the list of document entries.
@router.get("/api/documents")
def list_documents(_=Depends(get_authenticated_user), category: str | None = None, db=Depends(get_db)):
    statement = select(Document)

    if category:
        statement = statement.where(Document.category.ilike(category.lower()))

    documents = db.scalars(statement).all()

    result = []

    for document in documents:
        entry = document_dict(document)
        result.append(entry)

    return {"documents": result}


# Returns a short-lived signed URL that lets the browser open a stored PDF.
# Takes: path - the storage-relative path of the file.
# Returns: a dict containing the signed file URL.
# Raises: HTTPException 404 if the file's top-level folder is not allowed.
@router.get("/api/documents/file-url")
def get_document_file_url(path: str = Query(...), _=Depends(get_authenticated_user)):
    top_level_folder = path.split("/", 1)[0]

    if top_level_folder not in ALLOWED_STORAGE_ROOTS:
        raise HTTPException(status_code=404, detail="File not found")

    token = sign_file_link(path)
    signed_url = f"/api/documents/file?token={quote(token, safe='')}"

    return {"url": signed_url}


# Serves a stored file, protected by a short-lived signed token.
# Takes: token - the signed file token from get_document_file_url.
# Returns: the file as a FileResponse.
# Raises: HTTPException 403 if invalid/expired, 404 if the file is missing.
@router.get("/api/documents/file")
def get_document_file(token: str = Query(...)):
    relative_path = verify_file_link(token)

    if not relative_path:
        raise HTTPException(status_code=403, detail="Invalid or expired link")

    file_path = STORAGE_DIR / relative_path

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Serve inline (no attachment filename) so browsers open the file in a tab
    # instead of downloading it. The media type is inferred from the extension.
    return FileResponse(path=file_path)


# Returns every document category currently in use.
# The list is the union of categories present in the documents table and the
# category folders on disk, so newly added "Other" categories show up too.
# Takes: none (requires the admin role).
# Returns: a dict whose "categories" value is the sorted list of category names.
@router.get("/api/admin/categories")
def list_document_categories(_=Depends(require_admin), db=Depends(get_db)):
    categories = set()

    for (category,) in db.execute(select(Document.category).distinct()):
        if category:
            categories.add(_display_category(category))

    # Every storage folder is a valid category (folders created via "Other").
    for folder in ALLOWED_STORAGE_ROOTS:
        categories.add(_display_category(folder))

    return {"categories": sorted(categories)}


# Uploads a new company document.
# The file is saved inside storage/<category>/ and a matching Document row is
# added, so the document is instantly visible to every user in the normal
# documents section.
# Takes:
#   name     - the document's display name.
#   category - the category folder to save into.
#   access   - access level: "public" for everyone or "admin" for admins only.
#   file     - the uploaded PDF/file.
# Returns: a dict with the new document's details.
# Raises: HTTPException 400 on invalid input.
@router.post("/api/admin/documents")
async def upload_document(
    file: UploadFile = File(...),
    name: str = Form(...),
    category: str = Form(...),
    _=Depends(require_admin),
    db=Depends(get_db),
):
    safe_name = name.strip()

    if not safe_name:
        raise HTTPException(status_code=400, detail="Document name is required")

    category = category.strip()

    if not category:
        raise HTTPException(status_code=400, detail="Category is required")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")

    safe_category = _safe_category(category)

    # Allow newly created category folders to be served immediately.
    if safe_category not in ALLOWED_STORAGE_ROOTS:
        ALLOWED_STORAGE_ROOTS.append(safe_category)
        ALLOWED_STORAGE_ROOTS.sort()

    # Keep the original filename (matching the existing storage layout), but
    # fall back to the document name when the upload has no extension.
    original_filename = Path(file.filename or "").name or f"{safe_name}.pdf"
    target_folder = STORAGE_DIR / safe_category
    target_folder.mkdir(parents=True, exist_ok=True)
    target_path = target_folder / original_filename

    counter = 1

    while target_path.exists():
        stem = target_path.stem
        suffix = target_path.suffix
        target_path = target_folder / f"{stem} ({counter}){suffix}"
        counter += 1

    content = await file.read()

    try:
        target_path.write_bytes(content)
    except OSError:
        raise HTTPException(status_code=500, detail="Could not save the file")

    document_id = _next_document_id(db)
    relative_file = f"{safe_category}/{target_path.name}"
    file_type = (target_path.suffix.lstrip(".") or "PDF").upper()

    document = Document(
        document_id=document_id,
        name=safe_name,
        category=safe_category,
        file=relative_file,
        type=file_type,
        # New documents are not enabled for AI until an admin turns them on.
        ai_enabled=False,
        ai_status="not_indexed",
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    return document_dict(document)


# Deletes a company document: removes its database row and the stored file.
# If no documents remain in that category, the category folder is removed too,
# so an empty category disappears from the sidebar everywhere.
# Takes: document_id - the id of the document to delete.
# Returns: a dict confirming the deletion.
# Raises: HTTPException 404 if the document does not exist.
@router.delete("/api/admin/documents/{document_id}")
def delete_document(document_id: str, _=Depends(require_admin), db=Depends(get_db)):
    document = db.get(Document, document_id)

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    relative_file = document.file
    category = document.category

    # Remove the document's chunks/vectors so it is no longer used by AI.
    removed_chunks = 0
    if document.ai_enabled:
        try:
            removed_chunks = deindex_document(document_id)
        except Exception:
            # Best-effort: never fail the deletion because ChromaDB hiccuped.
            pass

    db.delete(document)
    db.commit()

    # Best-effort removal of the physical file; never fail the request if the
    # file is already missing.
    if relative_file:
        file_path = STORAGE_DIR / relative_file

        try:
            if file_path.is_file():
                file_path.unlink()
        except OSError:
            pass

    # If this was the last document in the category, remove the category folder
    # (and its now-empty parent, if any) so it stops appearing everywhere.
    removed_category = False
    remaining = db.scalar(select(Document).where(Document.category == category))

    if remaining is None:
        removed_category = _remove_category_folder(category)

    return {
        "status": "deleted",
        "document_id": document_id,
        "name": document.name,
        "removed_category": removed_category,
        "removed_ai_chunks": removed_chunks,
        "category": category if removed_category else None,
    }


# Returns the AI/RAG state for every document, used by the admin UI to render
# each document's "use for AI" toggle and its indexing status.
# Takes: none (requires the admin role).
# Returns: a dict whose "documents" value maps document_id -> {ai_enabled, ai_status}.
@router.get("/api/admin/documents/ai-status")
def list_ai_document_status(_=Depends(require_admin), db=Depends(get_db)):
    documents = db.scalars(select(Document)).all()

    return {
        "documents": {
            doc.document_id: {
                "ai_enabled": bool(doc.ai_enabled),
                "ai_status": normalize_status(doc.ai_status),
            }
            for doc in documents
        }
    }


# Enables or disables a document for AI chat, indexing or removing its chunks.
# Enabling indexes the PDF into ChromaDB (only if the file changed or it is not
# indexed yet); disabling removes its vectors so it is no longer used by AI.
# Takes: document_id - the document to enable/disable.
#        enabled - true to index the document, false to deindex it.
# Returns: the document's updated AI state plus how many chunks were written.
# Raises: HTTPException 400/404 on invalid input or missing document.
@router.post("/api/admin/documents/{document_id}/ai")
def set_document_ai(
    document_id: str,
    enabled: bool = Query(..., description="Enable (true) or disable (false) AI"),
    _=Depends(require_admin),
    db=Depends(get_db),
):
    document = db.get(Document, document_id)

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Resolve the explicit true/false query param into a boolean toggle.
    enable = bool(enabled)

    if not enable:
        # Turn off AI use for this PDF. The indexed chunks are kept in ChromaDB
        # so re-enabling later is instant, but the document stops being searched.
        # The status stays "ready" (it is still indexed) while ai_enabled=False,
        # which the admin UI shows under "Ready but Disabled".
        document.ai_enabled = False
        document.ai_status = "ready" if is_indexed(document_id) else "not_indexed"
        document.ai_updated_at = datetime.utcnow().isoformat(timespec="seconds")
        db.commit()
        db.refresh(document)

        return {
            "document_id": document_id,
            "ai_enabled": False,
            "ai_status": document.ai_status,
            "chunks_written": 0,
            "chunks_removed": 0,
        }

    documentation_already_indexed = is_indexed(document_id)

    if documentation_already_indexed:
        # Already embedded from a previous enable: just turn it back on without
        # re-running the expensive embedding step.
        document.ai_enabled = True
        document.ai_status = "ready"
        document.ai_updated_at = datetime.utcnow().isoformat(timespec="seconds")
        db.commit()
        db.refresh(document)

        return {
            "document_id": document_id,
            "ai_enabled": True,
            "ai_status": "ready",
            "chunks_written": 0,
            "chunks_removed": 0,
        }

    document.ai_enabled = True
    document.ai_status = "indexing"
    document.ai_updated_at = datetime.utcnow().isoformat(timespec="seconds")
    db.commit()

    def report_status(status):
        document.ai_status = status
        db.commit()

    try:
        if document.file:
            chunks_written = index_document(document, report_status=report_status)
            document.ai_status = "ready"
        else:
            raise ValueError("Document has no stored file to index")
    except Exception as exc:
        document.ai_status = "error"
        db.commit()
        # Return an error state so the UI can show it, rather than raising.
        return {
            "document_id": document_id,
            "ai_enabled": True,
            "ai_status": "error",
            "error": str(exc),
            "chunks_written": 0,
            "chunks_removed": 0,
        }

    db.commit()
    db.refresh(document)

    return {
        "document_id": document_id,
        "ai_enabled": True,
        "ai_status": "ready",
        "chunks_written": chunks_written,
        "chunks_removed": 0,
    }


def _remove_category_folder(category):
    """Delete an empty category folder from storage.

    Removes the top-level folder and any leftover empty sub-directories under
    it. Only empty directories are ever removed, so real files are never touched.
    Also removes the category from the in-memory allowed list so the sidebar
    picks up the change immediately.

    Takes: category - the category folder to remove.
    Returns: True when the folder was removed, False otherwise.
    """
    if not category:
        return False

    folder = STORAGE_DIR / category

    if not folder.is_dir():
        return False

    try:
        for root, dirs, files in os.walk(folder, topdown=False):
            for name in dirs:
                empty_dir = Path(root) / name

                try:
                    empty_dir.rmdir()
                except OSError:
                    pass

        folder.rmdir()
    except OSError:
        return False

    # Also remove from the in-memory allowed list so the sidebar picks it up.
    if category in ALLOWED_STORAGE_ROOTS:
        ALLOWED_STORAGE_ROOTS.remove(category)

    return True


def _safe_category(raw_category):
    """Normalise a category into a safe storage folder name.

    Only safe characters are kept and the result is lowercased so DB and
    storage folder always match, regardless of how the user typed it.
    Takes: raw_category - the raw category string.
    Returns: a cleaned, lowercased folder name.
    """
    cleaned = "".join(ch for ch in raw_category if ch.isalnum() or ch in (" ", "-", "_")).strip()
    cleaned = " ".join(cleaned.lower().split())

    if not cleaned:
        raise HTTPException(status_code=400, detail="Category cannot be empty")

    return cleaned[:40]


def _display_category(raw_category):
    """Return a title-cased version of a category for display in the UI."""
    if not raw_category:
        return raw_category
    return raw_category.title()


def _next_document_id(db):
    """Return the next DOCnnn identifier in sequence.

    Takes: db - the database session.
    Returns: a document id string one higher than the current maximum.
    """
    existing_ids = db.scalars(select(Document.document_id)).all()
    max_number = 0

    for doc_id in existing_ids:
        suffix = ""

        for ch in doc_id:
            if ch.isdigit():
                suffix += ch

        if suffix:
            max_number = max(max_number, int(suffix))

    return f"DOC{max_number + 1:03d}"


def service_dict(service):
    """Convert a Service database row into a plain dict.

    Takes: service - a Service object.
    Returns: a dict representing the service entry.
    """
    return {
        "service_id": service.service_id,
        "name": service.name,
        "role": service.role,
        "department": service.department,
        "extension": service.extension,
        "email": service.email,
        "location": service.location,
        "hours": service.hours,
    }


def document_dict(document):
    """Convert a Document database row into a plain dict.

    The category is title-cased for display so the frontend always sees
    consistent casing (e.g. "company policy") regardless of what was
    stored in the database.
    Takes: document - a Document object.
    Returns: a dict representing the document entry.
    """
    return {
        "document_id": document.document_id,
        "name": document.name,
        "category": _display_category(document.category),
        "file": document.file,
        "type": document.type,
        "ai_enabled": bool(document.ai_enabled),
        "ai_status": normalize_status(document.ai_status),
    }
