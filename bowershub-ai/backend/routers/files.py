"""
File API routes: upload, serve, thumbnails.
"""

import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse

from backend.middleware.auth import get_current_user
from backend.services.file_manager import FileManager, FileValidationError
from backend.database import get_pool

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/upload")
async def upload_files(
    request: Request,
    files: List[UploadFile] = File(...),
    user: dict = Depends(get_current_user),
):
    """Upload one or more files. Returns asset metadata for each."""
    if len(files) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 files per upload")

    config = request.app.state.config
    file_manager = FileManager(config)

    # Get conversation_id from form data or query param
    form = await request.form()
    conversation_id = int(form.get("conversation_id", 0))

    results = []
    for upload_file in files:
        content = await upload_file.read()
        mime = upload_file.content_type or "application/octet-stream"
        filename = upload_file.filename or "unnamed"

        try:
            asset = await file_manager.upload(
                file_content=content,
                filename=filename,
                mime_type=mime,
                conversation_id=conversation_id,
                user_id=user["id"],
            )
            results.append(asset)
        except FileValidationError as e:
            results.append({"error": str(e), "filename": filename})

    return {"files": results}


@router.get("/{asset_id}")
async def serve_file(asset_id: str, request: Request, user: dict = Depends(get_current_user)):
    """Serve a file by asset ID (with auth check)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT path, mime, original_name FROM files.assets WHERE id = $1::uuid",
            asset_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="File not found")

    config = request.app.state.config
    file_manager = FileManager(config)
    full_path = file_manager.get_file_path(row["path"])

    if not full_path:
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=full_path,
        media_type=row["mime"],
        filename=row["original_name"],
    )


@router.get("/{asset_id}/thumbnail")
async def serve_thumbnail(asset_id: str, request: Request, user: dict = Depends(get_current_user)):
    """Serve a thumbnail for an image asset."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT path, mime FROM files.assets WHERE id = $1::uuid",
            asset_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="File not found")

    if not row["mime"].startswith("image/"):
        raise HTTPException(status_code=400, detail="Not an image")

    config = request.app.state.config
    file_manager = FileManager(config)
    thumb_path = file_manager.get_thumbnail_path(row["path"])

    if not thumb_path:
        raise HTTPException(status_code=404, detail="Thumbnail not available")

    return FileResponse(path=thumb_path, media_type=row["mime"])
