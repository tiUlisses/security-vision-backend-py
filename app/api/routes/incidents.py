# app/api/routes/incidents.py
from typing import List, Optional
from datetime import datetime, timezone
import asyncio
import logging
import mimetypes
import uuid
from tempfile import SpooledTemporaryFile
from urllib.request import urlopen
from app.services.chatwoot_client import ChatwootClient

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Form,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.incident_files import (
    save_incident_file,
    save_incident_image_from_url,  # 👈 novo
)

from app.services.incidents import (
    apply_incident_update,
    compute_sla_fields,
    infer_incident_kind_from_event,
    extract_media_from_event,
)
from app.api.deps import get_db_session, get_current_active_user
from app.models.user import User

from app.crud import (
    incident as crud_incident,
    device_event as crud_device_event,
    device as crud_device,
    incident_message as crud_incident_message,
)
from app.schemas import (
    IncidentCreate,
    IncidentRead,
    IncidentUpdate,
    IncidentFromDeviceEventCreate,
    IncidentMessageCreate,
    IncidentMessageRead,
)

logger = logging.getLogger(__name__)
chatwoot_client = ChatwootClient()
router = APIRouter()


# ---------------------------------------------------------------------------
# LIST / GET
# ---------------------------------------------------------------------------


@router.get("/my", response_model=List[IncidentRead])
async def list_my_incidents(
    skip: int = 0,
    limit: int = 100,
    only_open: bool = False,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    """
    Lista apenas incidentes visíveis para o operador logado:
    - atribuídos diretamente a ele
    - em que ele é assignee
    - atribuídos a grupos dos quais ele é membro
    - gerais (sem grupo e sem responsável)
    """
    return await crud_incident.list_for_user(
        db,
        user_id=current_user.id,
        only_open=only_open,
        skip=skip,
        limit=limit,
    )

@router.get("/", response_model=List[IncidentRead])
async def list_incidents(
    skip: int = 0,
    limit: int = 100,
    only_open: bool = False,
    device_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    """
    Lista incidentes.

    - `only_open=true` -> só OPEN/IN_PROGRESS
    - `device_id` -> filtra por dispositivo (câmera)
    """
    # (não usamos current_user diretamente aqui, apenas forçamos autenticação)

    if device_id is not None:
        return await crud_incident.list_by_device(
            db,
            device_id=device_id,
            only_open=only_open,
            skip=skip,
            limit=limit,
        )

    if only_open:
        return await crud_incident.list_open(
            db,
            skip=skip,
            limit=limit,
        )

    return await crud_incident.get_multi(db, skip=skip, limit=limit)


@router.get("/{incident_id}", response_model=IncidentRead)
async def get_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    """
    Detalhe de um incidente.
    """
    db_inc = await crud_incident.get(db, id=incident_id)
    if not db_inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    return db_inc


# ---------------------------------------------------------------------------
# CREATE (manual)
# ---------------------------------------------------------------------------


@router.post("/", response_model=IncidentRead, status_code=status.HTTP_201_CREATED)
async def create_incident(
    incident_in: IncidentCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    """
    Cria um incidente manualmente.
    """
    now = datetime.now(timezone.utc)

    sla_minutes, due_at = compute_sla_fields(
        severity=incident_in.severity,
        sla_minutes=incident_in.sla_minutes,
        due_at=incident_in.due_at,
        now=now,
    )

    data = incident_in.model_dump()

    # ❌ NÃO é coluna do model Incident (é conceito de relacionamento N:N)
    data.pop("assignee_ids", None)

    # Incidente manual não deve ser vinculado direto a um DeviceEvent
    data["device_event_id"] = None

    data["sla_minutes"] = sla_minutes
    data["due_at"] = due_at
    data["created_by_user_id"] = current_user.id

    db_inc = await crud_incident.create(db, obj_in=data)
     # -------------------------------------
    # Chatwoot: melhor esforço
    # -------------------------------------
    if chatwoot_client.is_configured():
        try:
            conv_id = await chatwoot_client.send_incident_notification(db_inc)
            if conv_id and conv_id != db_inc.chatwoot_conversation_id:
                # persiste o conversation_id no incidente
                db_inc = await crud_incident.update(
                    db,
                    db_obj=db_inc,
                    obj_in={"chatwoot_conversation_id": conv_id},
                )
        except Exception:
            logger.exception(
                "[chatwoot] falha ao enviar notificação do incidente %s",
                db_inc.id,
            )


    return db_inc

# ---------------------------------------------------------------------------
# CREATE a partir de um DeviceEvent específico (por ex. na tela da câmera)
# ---------------------------------------------------------------------------


@router.post(
    "/from-device-event/{device_event_id}",
    response_model=IncidentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_incident_from_device_event(
    device_event_id: int,
    payload: IncidentFromDeviceEventCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    """
    Cria incidente diretamente a partir de um DeviceEvent.

    Body JSON:
    {
      "title": "...",
      "description": "...",
      "severity": "LOW|MEDIUM|HIGH|CRITICAL"
    }
    """
    dev_event = await crud_device_event.get(db, id=device_event_id)
    if not dev_event:
        raise HTTPException(status_code=404, detail="DeviceEvent not found")

    device = await crud_device.get(db, id=dev_event.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if device.type != "CAMERA":
        raise HTTPException(
            status_code=400,
            detail="Incidents from events are currently supported only for CAMERA devices",
        )

    # Aqui poderíamos estender o crud_incident.create_from_device_event
    # para aceitar created_by_user_id, se sua função já tiver esse parâmetro.
    # Para não quebrar nada existente, por enquanto só criamos o incidente
    # e deixamos o serviço interno usar defaults.
    db_inc = await crud_incident.create_from_device_event(
        db,
        device_event=dev_event,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        kind="CAMERA_ISSUE",
    )
    return db_inc


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------


@router.patch("/{incident_id}", response_model=IncidentRead)
async def update_incident(
    incident_id: int,
    incident_in: IncidentUpdate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    """
    Atualiza um incidente.
    """
    db_inc = await crud_incident.get(db, id=incident_id)
    if not db_inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    updated = await apply_incident_update(
        db,
        incident=db_inc,
        update_in=incident_in,
        actor_user_id=current_user.id,  # 👈 antes era None
    )
    return updated


# ---------------------------------------------------------------------------
# MESSAGES (timeline / chat)
# ---------------------------------------------------------------------------


@router.get(
    "/{incident_id}/messages",
    response_model=list[IncidentMessageRead],
)
async def list_incident_messages(
    incident_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    """
    Lista mensagens da timeline de um incidente.
    """
    db_inc = await crud_incident.get(db, id=incident_id)
    if not db_inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    msgs = await crud_incident_message.list_by_incident(
        db,
        incident_id=incident_id,
        limit=500,
    )
    return msgs


@router.post(
    "/{incident_id}/messages",
    response_model=IncidentMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_incident_message(
    incident_id: int,
    msg_in: IncidentMessageCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    db_inc = await crud_incident.get(db, id=incident_id)
    if not db_inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    msg_data = msg_in.model_dump()
    msg_data["incident_id"] = incident_id

    # garante que é COMMENT se vier vazio
    msg_data.setdefault("message_type", "COMMENT")

    # 👇 grava o nome do operador
    msg_data["author_name"] = current_user.full_name

    db_msg = await crud_incident_message.create(db, obj_in=msg_data)

    # 🔹 envia também pro Chatwoot (best effort, sem quebrar a API)
    try:
        await chatwoot_client.send_incident_timeline_message(
            db_inc,
            db_msg,
        )
    except Exception:
        logger.exception(
            "[chatwoot] erro ao enviar comentário %s do incidente %s para o Chatwoot",
            db_msg.id,
            db_inc.id,
        )

    return db_msg


# ---------------------------------------------------------------------------
# CREATE a partir de qualquer DeviceEvent (payload mais completo)
# ---------------------------------------------------------------------------


@router.post(
    "/from-event",
    response_model=IncidentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_incident_from_event(
    body: IncidentFromDeviceEventCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    """
    Cria incidente a partir de um DeviceEvent (campo device_event_id em body).

    - Cria o incidente já com status OPEN
    - Gera uma mensagem SYSTEM com o contexto do evento
    - Tenta baixar snapshot / face cadastrada como mensagens MEDIA
    """
    db_event = await crud_device_event.get(db, id=body.device_event_id)
    if not db_event:
        raise HTTPException(status_code=404, detail="DeviceEvent not found")

    db_device = await crud_device.get(db, id=db_event.device_id)
    if not db_device:
        raise HTTPException(status_code=404, detail="Device not found")

    severity = (body.severity or "MEDIUM").upper()

    default_title = f"Incidente de câmera (evento {db_event.analytic_type})"
    title = body.title or default_title

    default_description = (
        f"Incidente gerado automaticamente a partir do evento {db_event.id} "
        f"({db_event.analytic_type}) do dispositivo {db_device.name}."
    )
    description = body.description or default_description

    tenant = body.tenant
    payload = db_event.payload or {}
    if tenant is None and isinstance(payload, dict):
        tenant = payload.get("tenant")

    kind = infer_incident_kind_from_event(db_event)

    now = datetime.now(timezone.utc)
    sla_minutes, due_at = compute_sla_fields(
        severity=severity,
        sla_minutes=body.sla_minutes,
        now=now,
    )

    # ------------------------------------------------------------------
    # Cria o incidente
    # ------------------------------------------------------------------
    data = {
        "device_id": db_event.device_id,
        "device_event_id": db_event.id,
        "kind": kind,
        "tenant": tenant,
        "status": "OPEN",
        "severity": severity,
        "title": title,
        "description": description,
        "sla_minutes": sla_minutes,
        "due_at": due_at,
        "created_by_user_id": current_user.id,
    }

    db_inc = await crud_incident.create(db, obj_in=data)

    # ------------------------------------------------------------------
    # 1) Mensagem SYSTEM de contexto (primeira da timeline)
    # ------------------------------------------------------------------
    analytic_raw = payload.get("AnalyticType") or db_event.analytic_type or ""
    analytic = str(analytic_raw)

    camera_name = (
        payload.get("CameraName")
        or getattr(db_device, "name", None)
        or f"Câmera {db_device.id}"
    )

    ts_raw = (
        payload.get("Timestamp")
        or payload.get("timestamp")
        or db_event.occurred_at
        or db_event.created_at
    )
    ts_str = None
    if isinstance(ts_raw, str):
        # Se for string, mostramos direto (para não correr risco de parse dar erro)
        ts_str = ts_raw
    elif isinstance(ts_raw, datetime):
        ts_str = ts_raw.isoformat()

    building = payload.get("Building")
    floor = payload.get("Floor")
    meta = payload.get("Meta") or {}

    # Dados de face reconhecida (se houver)
    ff_name = meta.get("ff_person_name") or meta.get("person_name")
    ff_confidence = meta.get("ff_confidence")

    lines: list[str] = []
    lines.append(
        f"Incidente criado automaticamente a partir do evento **{analytic}** "
        f"na câmera **{camera_name}**."
    )

    if ts_str:
        lines.append(f"Horário do evento: {ts_str}.")

    if building or floor:
        partes = []
        if building:
            partes.append(f"Prédio: {building}")
        if floor:
            partes.append(f"Andar/Setor: {floor}")
        lines.append("Local: " + " • ".join(partes) + ".")

    if ff_name:
        lines.append(f"Pessoa reconhecida: **{ff_name}**.")
        if isinstance(ff_confidence, (int, float)):
            lines.append(f"Confiança do match: {(ff_confidence * 100):.1f}%.")

    # Severidade / fluxo
    lines.append(f"Severidade: **{severity}**. Status inicial: **OPEN**.")
    lines.append(
        "Este incidente foi aberto manualmente a partir da tela de eventos "
        "de câmera pelo operador "
        f"**{current_user.full_name or current_user.email}**."
    )

    system_content = "\n".join(lines)

    system_msg_data = {
        "incident_id": db_inc.id,
        "message_type": "SYSTEM",
        "content": system_content,
        "author_name": "Sistema",
    }
    await crud_incident_message.create(db, obj_in=system_msg_data)

    # ------------------------------------------------------------------
    # 2) Mídias derivadas do evento (snapshot, face cadastrada, etc.)
    # ------------------------------------------------------------------
    media_descriptors = extract_media_from_event(db_event)
    # Esperado: lista de dicts tipo:
    # {
    #   "source_url": "...",
    #   "filename_hint": "...",
    #   "label": "Snapshot do evento ...",
    # }

    for media in media_descriptors:
        url = media.get("source_url")
        if not url:
            continue

        try:
            media_url, media_type, original_name = await save_incident_image_from_url(
                incident_id=db_inc.id,
                url=url,
                filename_hint=media.get("filename_hint"),
            )
        except Exception as exc:
            # Apenas loga e segue. Não queremos quebrar a criação do incidente.
            print(
                f"[incidents] Falha ao baixar mídia '{url}' "
                f"para incidente {db_inc.id}: {exc}"
            )
            continue

        msg_data = {
            "incident_id": db_inc.id,
            "message_type": "MEDIA",
            "media_type": media_type or "IMAGE",
            "media_url": media_url,
            "media_thumb_url": None,
            "media_name": original_name,
            "content": media.get("label"),
            "author_name": "Sistema",
        }

        await crud_incident_message.create(db, obj_in=msg_data)
    
        # Ao final (antes do return db_inc):
    if chatwoot_client.is_configured():
        try:
            conv_id = await chatwoot_client.send_incident_notification(db_inc)
            if conv_id and conv_id != db_inc.chatwoot_conversation_id:
                db_inc = await crud_incident.update(
                    db,
                    db_obj=db_inc,
                    obj_in={"chatwoot_conversation_id": conv_id},
                )
        except Exception:
            logger.exception(
                "[chatwoot] erro ao enviar notificação Chatwoot para incidente %s",
                db_inc.id,
            )


    return db_inc

@router.post(
    "/{incident_id}/attachments",
    response_model=IncidentMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_incident_attachment(
    incident_id: int,
    file: UploadFile = File(...),
    description: str | None = Form(None),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    """
    Faz upload de um arquivo e cria uma mensagem de mídia na timeline do incidente.

    - Aceita qualquer tipo de arquivo (imagem, vídeo, áudio, documento, etc.).
    - Salva em disco via save_incident_file.
    - Cria uma IncidentMessage do tipo MEDIA ligada ao incidente.
    """
    # Garante que o incidente existe
    db_inc = await crud_incident.get(db, id=incident_id)
    if not db_inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Salva o arquivo no storage (media/incidents/{incident_id}/...)
    media_url, media_type, original_name = await save_incident_file(
        incident_id=incident_id,
        file=file,
    )

    # Usa a descrição, se o operador escreveu algo, senão um texto padrão
    content = description or f"Arquivo anexado: {original_name}"

    msg_data = {
        "incident_id": incident_id,
        "message_type": "MEDIA",
        "content": content,
        "media_type": media_type,           # IMAGE / VIDEO / AUDIO / FILE
        "media_url": media_url,             # URL pública gerada por save_incident_file
        "media_thumb_url": None,
        "media_name": original_name,
        "author_name": current_user.full_name,  # Nome do operador que anexou
    }

    db_msg = await crud_incident_message.create(db, obj_in=msg_data)
        # 🔹 envia também pro Chatwoot (best effort)
    try:
        await chatwoot_client.send_incident_timeline_message(
            db_inc,
            db_msg,
        )
    except Exception:
        logger.exception(
            "[chatwoot] erro ao enviar anexo %s do incidente %s para o Chatwoot",
            db_msg.id,
            db_inc.id,
        )
    return db_msg