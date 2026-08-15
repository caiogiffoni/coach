"""Upload safety guards: size limits, filename sanitization, zip extraction safety."""

import os
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile, status


def validate_upload_count(files: list[UploadFile], max_count: int) -> None:
    """Reject requests with too many files."""
    if len(files) > max_count:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Too many files: {len(files)} (max {max_count})",
        )


def sanitize_filename(filename: str | None) -> str:
    """Return a safe filename with no path separators or parent references."""
    if not filename:
        return "unknown"
    name = os.path.basename(filename).strip()
    if not name or name in {".", ".."}:
        return "unknown"
    # Neutralize any remaining path-like fragments.
    return name.replace(os.sep, "_").replace("/", "_").replace("\\", "_")


def save_upload_limited(
    upload: UploadFile,
    dest: Path,
    max_bytes: int,
) -> int:
    """Stream an upload to disk, aborting if it exceeds max_bytes.

    Returns the number of bytes written.
    Raises HTTPException(413) if the limit is exceeded.
    """
    written = 0
    with open(dest, "wb") as f:
        for chunk in upload.file:
            written += len(chunk)
            if written > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds maximum size of {max_bytes} bytes",
                )
            f.write(chunk)
    return written


def _safe_member_path(member: zipfile.ZipInfo, target_dir: Path) -> Path | None:
    """Resolve a zip member inside target_dir, returning None if it escapes."""
    target = Path(target_dir).resolve()
    member_path = Path(member.filename)
    # Reject absolute paths and parent references explicitly.
    if member_path.is_absolute():
        return None
    parts = member_path.parts
    if any(part == ".." or part.startswith("/") for part in parts):
        return None
    final = (target / member_path).resolve()
    try:
        final.relative_to(target)
    except ValueError:
        return None
    return final


def extract_zip_safely(
    zip_path: Path,
    target_dir: Path,
    max_uncompressed_bytes: int,
    max_ratio: int,
) -> None:
    """Extract a zip file guarding against path traversal and zip bombs.

    Raises ValueError on unsafe content.
    """
    target = Path(target_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        total_uncompressed = 0
        for info in zf.infolist():
            safe_path = _safe_member_path(info, target)
            if safe_path is None:
                raise ValueError(
                    f"Zip contains unsafe path: {info.filename!r}"
                )

            uncompressed = info.file_size
            compressed = info.compress_size or uncompressed or 1
            if uncompressed > 0 and uncompressed // compressed > max_ratio:
                raise ValueError(
                    f"Zip entry {info.filename!r} has suspicious "
                    f"compression ratio ({uncompressed // compressed}x)"
                )

            total_uncompressed += uncompressed
            if total_uncompressed > max_uncompressed_bytes:
                raise ValueError(
                    f"Zip would exceed max uncompressed size "
                    f"({max_uncompressed_bytes} bytes)"
                )

        zf.extractall(target)
