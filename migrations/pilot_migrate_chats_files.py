"""
Pilot: тестовая миграция B24 → PosPro для ОДНОЙ сделки и ОДНОЙ задачи.

Что делает:
  1. Для сделки b24_id=66589:
     - Находит pospro Deal через b24_mirror
     - Находит/создаёт ChatRoom(kind=deal, related_deal_id=d.id) + members
     - Для каждого коммента из crm.timeline.comment.list создаёт ChatMessage
       (author_id через user_map, created_at из CREATED)
     - Идемпотентность: b24_mirror(entity_type='chat_msg', b24_id=comment.ID)
  2. Для задачи b24_id=10143:
     - Находит pospro Task через b24_mirror
     - Для каждого файла из UF_TASK_WEBDAV_FILES:
       * Скачивает с B24 (DOWNLOAD_URL уже содержит auth)
       * Кладёт в /disk/uploads/crm_attachments/task/<pid>/<ts>_<name>
       * Создаёт EntityAttachment
     - Идемпотентность: b24_mirror(entity_type='task_file', b24_id=ATTACHMENT_ID)

Dry-run по умолчанию.

Запуск:
    python -u -m migrations.pilot_migrate_chats_files
    python -u -m migrations.pilot_migrate_chats_files --apply
"""

import argparse
import mimetypes
import os
import sys
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from models.chat import ChatRoom, ChatMember, ChatMessage, ChatAttachment
from models.entity_attachment import EntityAttachment
from models.deal import Deal, DealMember
from models.task import Task, TaskMember
from models.systemuser import SystemUser

from migrations.bitrix24._b24 import call
from migrations.bitrix24._utils import (
    load_mapping, user_pospro_id, mirror_get, mirror_set,
)


B24_HOST = 'https://pospro24.bitrix24.kz'
ATTACHMENTS_SUBFOLDER = 'crm_attachments'


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--deal-b24', type=str, default='66589')
    p.add_argument('--task-b24', type=str, default='10143')
    return p.parse_args()


def _parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace('Z', '+00:00'))
    except Exception:
        return None


def _get_or_create_deal_room(deal: Deal) -> ChatRoom:
    room = ChatRoom.query.filter_by(kind='deal', related_deal_id=deal.id).first()
    if room:
        return room
    room = ChatRoom(kind='deal', related_deal_id=deal.id)
    db.session.add(room)
    db.session.flush()
    # members: creator + responsible + все DealMember
    allowed = set()
    if deal.creator_id:
        allowed.add(deal.creator_id)
    if deal.responsible_user_id:
        allowed.add(deal.responsible_user_id)
    for m in DealMember.query.filter_by(deal_id=deal.id).all():
        allowed.add(m.user_id)
    for uid in allowed:
        db.session.add(ChatMember(room_id=room.id, user_id=uid))
    return room


def _get_or_create_task_room(task: Task) -> ChatRoom:
    room = ChatRoom.query.filter_by(kind='task', related_task_id=task.id).first()
    if room:
        return room
    room = ChatRoom(kind='task', related_task_id=task.id)
    db.session.add(room)
    db.session.flush()
    allowed = set()
    if task.creator_id:
        allowed.add(task.creator_id)
    if task.responsible_id:
        allowed.add(task.responsible_id)
    for m in TaskMember.query.filter_by(task_id=task.id).all():
        allowed.add(m.user_id)
    for uid in allowed:
        db.session.add(ChatMember(room_id=room.id, user_id=uid))
    return room


def _ensure_member(room_id: int, user_id: int):
    """Если автор коммента не в комнате — добавить (иначе чужое сообщение
    без membership = битый state)."""
    if not user_id:
        return
    exists = ChatMember.query.filter_by(room_id=room_id, user_id=user_id).first()
    if not exists:
        db.session.add(ChatMember(room_id=room_id, user_id=user_id))


def _download_b24_file(download_url: str) -> bytes:
    """Качает файл с B24. DOWNLOAD_URL уже содержит auth[aplogin]/ap в query."""
    url = B24_HOST + download_url if download_url.startswith('/') else download_url
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def _save_file(entity_type: str, entity_id: int, name: str, data: bytes) -> tuple[str, str]:
    """Сохраняет на диск. Возвращает (disk_path, file_url)."""
    import re, unicodedata
    safe = unicodedata.normalize('NFKD', name)
    safe = re.sub(r'[/\\?%*:|"<>]', '_', safe).strip() or 'file'
    ts = int(time.time() * 1000)
    disk_name = f'{ts}_{safe}'
    root = app.config['UPLOAD_FOLDER']
    folder = os.path.join(root, ATTACHMENTS_SUBFOLDER, entity_type, str(entity_id))
    os.makedirs(folder, exist_ok=True)
    disk_path = os.path.join(folder, disk_name)
    with open(disk_path, 'wb') as f:
        f.write(data)
    file_url = f'/uploads/{ATTACHMENTS_SUBFOLDER}/{entity_type}/{entity_id}/{disk_name}'
    return disk_path, file_url


def _migrate_deal_comments(deal_b24: str, mapping: dict, apply_: bool) -> int:
    print(f'\n=== DEAL b24#{deal_b24} ===', flush=True)
    pospro_did = mirror_get('deal', deal_b24)
    if not pospro_did:
        print(f'  deal#{deal_b24} не в b24_mirror', flush=True)
        return 0
    deal = Deal.query.get(pospro_did)
    if not deal:
        print(f'  deal#{deal_b24} → pospro#{pospro_did} удалён локально', flush=True)
        return 0
    print(f'  pospro deal: #{deal.id} {deal.name!r}', flush=True)

    r = call('crm.timeline.comment.list', {
        'order[ID]': 'ASC',
        'filter[ENTITY_ID]': deal_b24,
        'filter[ENTITY_TYPE]': 'deal',
        'start': 0,
    })
    comments = r.get('result') or []
    total_api = r.get('total') or len(comments)
    print(f'  комментов в B24: {total_api}', flush=True)

    if not comments:
        return 0

    room = None
    if apply_:
        room = _get_or_create_deal_room(deal)
        db.session.flush()

    n_added = 0
    for c in comments:
        b24_cid = str(c.get('ID'))
        if mirror_get('chat_msg', b24_cid):
            continue  # уже мигрировали

        author_b24 = str(c.get('AUTHOR_ID') or '')
        author_pid = user_pospro_id(mapping, author_b24, 0)
        if not author_pid:
            # Если автор не смаплен — ставим owner с префиксом в тексте.
            owner = SystemUser.query.filter_by(is_owner=True).first()
            author_pid = owner.id if owner else 1

        text_body = c.get('COMMENT') or ''
        created_at = _parse_dt(c.get('CREATED'))

        print(f'    + comment#{b24_cid} author={author_b24}→#{author_pid} '
              f'at={created_at} text={text_body[:60]!r}', flush=True)

        if apply_:
            _ensure_member(room.id, author_pid)
            msg = ChatMessage(
                room_id=room.id,
                author_id=author_pid,
                text=text_body,
                created_at=created_at or datetime.utcnow(),
            )
            db.session.add(msg)
            db.session.flush()
            mirror_set('chat_msg', b24_cid, msg.id)
        n_added += 1

    if apply_:
        db.session.commit()
    return n_added


def _migrate_task_files(task_b24: str, mapping: dict, apply_: bool) -> int:
    print(f'\n=== TASK b24#{task_b24} ===', flush=True)
    pospro_tid = mirror_get('task', task_b24)
    if not pospro_tid:
        print(f'  task#{task_b24} не в b24_mirror', flush=True)
        return 0
    task = Task.query.get(pospro_tid)
    if not task:
        print(f'  task#{task_b24} → pospro#{pospro_tid} удалён локально', flush=True)
        return 0
    print(f'  pospro task: #{task.id} {task.title!r}', flush=True)

    r = call('task.item.getdata', {'ID': task_b24})
    data = r.get('result') or {}
    files = data.get('UF_TASK_WEBDAV_FILES') or []
    print(f'  файлов в UF_TASK_WEBDAV_FILES: {len(files) if isinstance(files, list) else 0}',
          flush=True)
    if not isinstance(files, list) or not files:
        return 0

    n_added = 0
    for f in files:
        aid = str(f.get('ATTACHMENT_ID') or '')
        if mirror_get('task_file', aid):
            continue
        name = f.get('NAME') or f'file_{aid}'
        download_url = f.get('DOWNLOAD_URL')
        print(f'    + file#{aid} {name!r} ({f.get("SIZE")}b) → downloading…',
              flush=True)
        if not download_url:
            print(f'      skip — нет DOWNLOAD_URL', flush=True)
            continue
        if not apply_:
            n_added += 1
            continue
        try:
            payload = _download_b24_file(download_url)
        except Exception as e:
            print(f'      DOWNLOAD FAIL: {e}', flush=True)
            continue
        disk_path, file_url = _save_file('task', task.id, name, payload)
        mime, _ = mimetypes.guess_type(name)
        ea = EntityAttachment(
            entity_type='task',
            entity_id=task.id,
            file_url=file_url,
            file_name=name,
            file_size=len(payload),
            mime_type=mime,
            uploaded_by=task.creator_id,
            uploaded_at=datetime.utcnow(),
        )
        db.session.add(ea)
        db.session.flush()
        mirror_set('task_file', aid, ea.id)
        print(f'      saved as {file_url}  EA#{ea.id}', flush=True)
        n_added += 1

    if apply_:
        db.session.commit()
    return n_added


def main() -> int:
    args = _parse_args()
    with app.app_context():
        mapping = load_mapping()
        print(f'mode={"APPLY" if args.apply else "DRY-RUN"}', flush=True)

        n_msg = _migrate_deal_comments(args.deal_b24, mapping, args.apply)
        n_file = _migrate_task_files(args.task_b24, mapping, args.apply)

        print(f'\n=== TOTALS ===', flush=True)
        print(f'  ChatMessage добавлено:    {n_msg}', flush=True)
        print(f'  EntityAttachment:         {n_file}', flush=True)
        if not args.apply:
            print('\nDRY-RUN — ничего не записано.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
