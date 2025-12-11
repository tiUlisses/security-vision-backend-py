# app/services/incident_files.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

from fastapi import UploadFile

from app.core.config import settings


def _get_media_root() -> Path:
    """
    Diretório base para salvar arquivos de mídia.
    Usa settings.MEDIA_ROOT se existir, senão 'media'.
    """
    base = getattr(settings, "MEDIA_ROOT", None)
    if base:
        return Path(base)
    return Path("media")


def guess_media_type_from_content_type(content_type: str | None) -> str:
    """
    Converte content-type (image/jpeg, video/mp4, ...) para:
    - IMAGE
    - VIDEO
    - AUDIO
    - FILE (default)
    """
    if not content_type:
        return "FILE"
    if content_type.startswith("image/"):
        return "IMAGE"
    if content_type.startswith("video/"):
        return "VIDEO"
    if content_type.startswith("audio/"):
        return "AUDIO"
    return "FILE"


async def save_incident_file(
    incident_id: int,
    file: UploadFile,
) -> Tuple[str, str, str]:
    """
    Salva o arquivo no disco (media/incidents/{incident_id}/...) e devolve:
    - media_url (URL pública)
    - media_type (IMAGE/VIDEO/AUDIO/FILE)
    - original_name (nome original do arquivo)
    """
    media_root = _get_media_root()
    incident_dir = media_root / "incidents" / str(incident_id)
    incident_dir.mkdir(parents=True, exist_ok=True)

    original_name = file.filename or "upload.bin"
    ext = Path(original_name).suffix

    # timestamp + nome "sanitizado"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    stem = Path(original_name).stem
    safe_stem = "".join(
        c if c.isalnum() or c in ("-", "_") else "_" for c in stem
    ) or "file"

    filename = f"{ts}_{safe_stem}{ext}"
    dest_path = incident_dir / filename

    # grava em chunks
    with dest_path.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

    # monta URL pública
    base_url = getattr(settings, "MEDIA_BASE_URL", None)
    if base_url:
        base_url = base_url.rstrip("/")
        media_url = f"{base_url}/incidents/{incident_id}/{filename}"
    else:
        # vai ser servido em /media/... (vamos montar já já)
        media_url = f"/media/incidents/{incident_id}/{filename}"

    media_type = guess_media_type_from_content_type(file.content_type)

    return media_url, media_type, original_name


async def save_incident_image_from_url(
    incident_id: int,
    url: str,
    filename_hint: str | None = None,
) -> tuple[str, str, str]:
    """
    Faz download de uma imagem remota (SnapshotURL, foto de face, etc.)
    e salva usando a mesma lógica de save_incident_file.

    Retorna (media_url, media_type, original_name).
    """
    # Download síncrono simples – como é algo pontual por incidente,
    # em geral é aceitável. Se depois quiser, trocamos para httpx/anyio.
    resp = urlopen(url)
    content = resp.read()
    content_type = resp.info().get_content_type() or "image/jpeg"

    ext = mimetypes.guess_extension(content_type) or ".jpg"

    if filename_hint:
        original_name = filename_hint
    else:
        parsed = urlparse(url)
        original_name = parsed.path.rsplit("/", 1)[-1] or "image"

    if "." not in original_name:
        original_name = f"{original_name}{ext}"

    upload = UploadFile(
        filename=original_name,
        file=BytesIO(content),
        content_type=content_type,
    )

    # reaproveita toda a lógica já existente de path/URL em save_incident_file
    media_url, media_type, saved_name = await save_incident_file(
        incident_id=incident_id,
        file=upload,
    )

    return media_url, media_type, saved_name