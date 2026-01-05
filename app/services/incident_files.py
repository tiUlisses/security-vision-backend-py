# app/services/incident_files.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple
from urllib.request import urlopen
from urllib.parse import urlparse
import mimetypes
import os
import uuid
from tempfile import SpooledTemporaryFile

from fastapi import UploadFile

from app.core.config import settings


def _get_media_root() -> Path:
    """
    Diretório base para salvar arquivos de mídia.
    Usa settings.MEDIA_ROOT se existir, senão 'media'.
    """
    return Path(settings.media_root)


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
    base_url = settings.MEDIA_BASE_URL
    if base_url:
        base_url = base_url.rstrip("/")
        media_url = f"{base_url}/incidents/{incident_id}/{filename}"
    else:
        # vai ser servido em /media/...
        media_url = f"/media/incidents/{incident_id}/{filename}"

    # 🔹 Em vez de depender de file.content_type (que pode não existir ou ser read-only),
    # tentamos primeiro pegar, e se não vier, inferimos pelo nome do arquivo.
    content_type = getattr(file, "content_type", None)
    if not content_type:
        guessed, _ = mimetypes.guess_type(original_name)
        content_type = guessed or "application/octet-stream"

    media_type = guess_media_type_from_content_type(content_type)

    return media_url, media_type, original_name


async def save_incident_image_from_url(
    incident_id: int,
    url: str,
    filename_hint: str | None = None,
) -> Tuple[str, str, str]:
    """
    Faz download de uma imagem via HTTP e delega para save_incident_file.

    Retorna (media_url, media_type, original_name)
    """
    # 1) Baixa o binário da imagem
    resp = urlopen(url)
    data = resp.read()

    # 2) Define um nome de arquivo amigável
    if not filename_hint:
        parsed = urlparse(url)
        basename = os.path.basename(parsed.path)
        if not basename:
            basename = f"snapshot-{uuid.uuid4().hex}.jpg"
        filename_hint = basename

    # 3) Cria um arquivo temporário em memória
    f = SpooledTemporaryFile()
    f.write(data)
    f.seek(0)

    # 4) Cria um UploadFile *sem* mexer em content_type
    upload = UploadFile(filename=filename_hint, file=f)

    # 5) Reaproveita a função de upload já existente
    media_url, media_type, original_name = await save_incident_file(
        incident_id=incident_id,
        file=upload,
    )

    return media_url, media_type, original_name
