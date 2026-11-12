"""Storage local. Todos os caminhos são resolvidos dentro de data_dir (anti path traversal)."""
import hashlib
import re
import uuid
from pathlib import Path
from typing import BinaryIO

from app.config import settings


def root() -> Path:
    p = settings.data_dir.resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_filename(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .") or "arquivo"
    return name[:200]


def resolve(uri: str) -> Path:
    base = root()
    p = (base / uri).resolve()
    if base != p and base not in p.parents:
        raise ValueError("caminho fora do storage")
    return p


def asset_dir(project_id: uuid.UUID, asset_id: uuid.UUID) -> str:
    return f"projects/{project_id}/assets/{asset_id}"


class UploadTooLarge(Exception):
    pass


def save_upload(uri: str, stream: BinaryIO, max_bytes: int) -> tuple[str, int]:
    dest = resolve(uri)
    dest.parent.mkdir(parents=True, exist_ok=True)
    h, size = hashlib.sha256(), 0
    try:
        with open(dest, "wb") as out:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise UploadTooLarge()
                h.update(chunk)
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return h.hexdigest(), size
