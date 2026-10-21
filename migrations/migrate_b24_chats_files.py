"""
Полная миграция B24 → PosPro:
  A) Комментарии сделок (crm.timeline.comment.list) → ChatMessage
  B) Комментарии задач (task.commentitem.getlist) → ChatMessage
  C) Файлы задач (UF_TASK_WEBDAV_FILES) → EntityAttachment + download
  D) Файлы сделок (UF type=file) → EntityAttachment + download

Автор сообщения:
  - смаплен в наш system_users через user_map → используем его
  - НЕ смаплен, но есть имя в B24 (user.get) → СОЗДАЁМ нового SystemUser
    (email b24_<id>@imported.local, random password, is_active=False)
    и запоминаем маппинг на лету
  - НЕ смаплен и имени нет (действительно удалённый) → привязываем к
    служебному юзеру «Удалённый пользователь B24» (создаётся один раз)

uploaded_by файла:
  - creator сущности если валиден в system_users
  - иначе NULL (uploaded_by nullable + ondelete=SET NULL)

Идемпотентность:
  - comment_id → b24_mirror(entity_type='chat_msg')
  - ATTACHMENT_ID → b24_mirror(entity_type='task_file' / 'deal_file')

CLI:
  python -u -m migrations.migrate_b24_chats_files
  python -u -m migrations.migrate_b24_chats_files --apply
  python -u -m migrations.migrate_b24_chats_files --phase A --apply
  python -u -m migrations.migrate_b24_chats_files --limit 50 --apply
"""

import argparse
import json
import mimetypes
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from models.chat import ChatRoom, ChatMember, ChatMessage
from models.entity_attachment import EntityAttachment
from models.deal import Deal, DealMember
from models.task import Task, TaskMember
from models.systemuser import SystemUser

from migrations.bitrix24._b24 import call, _webhook_base
from migrations.bitrix24._utils import (
    load_mapping, user_pospro_id, mirror_get, mirror_set,
)


B24_HOST = 'https://pospro24.bitrix24.kz'
ATTACHMENTS_SUBFOLDER = 'crm_attachments'
DELETED_SENTINEL_EMAIL = 'b24_deleted_user@imported.local'


# ========================================================================
# Args
# ========================================================================

def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--phase', choices=['A', 'B', 'C', 'D', 'all'], default='all',
                   help='Какую фазу запустить (default: all)')
    p.add_argument('--limit', type=int, default=0,
                   help='Обработать не больше N сущностей в фазе (для теста)')
    p.add_argument('--batch', type=int, default=50)
    p.add_argument('--sleep', type=float, default=0.0)
    return p.parse_args()


# ========================================================================
# B24 helpers
# ========================================================================

def _b24_batch(cmds: dict) -> dict:
    """POST /batch.json. cmds = {name: (method, params)}. Return {name: result}."""
    url = _webhook_base() + '/batch.json'
    flat = {'halt': 0}
    for name, (method, params) in cmds.items():
        qs = urllib.parse.urlencode(params or {}, doseq=True)
        flat[f'cmd[{name}]'] = f'{method}?{qs}' if qs else method
    data = urllib.parse.urlencode(flat, doseq=True).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read().decode('utf-8')
    out = json.loads(body)
    return (out.get('result') or {}).get('result') or {}


def _download_b24(url_rel_or_abs: str) -> bytes:
    url = B24_HOST + url_rel_or_abs if url_rel_or_abs.startswith('/') else url_rel_or_abs
    with urllib.request.urlopen(url, timeout=180) as resp:
        return resp.read()


# ========================================================================
# Author resolution (user_map + lazy-create missing)
# ========================================================================

def _get_or_create_deleted_user() -> SystemUser:
    u = SystemUser.query.filter_by(email=DELETED_SENTINEL_EMAIL).first()
    if u:
        return u
    u = SystemUser(
        full_name='Удалённый пользователь B24',
        email=DELETED_SENTINEL_EMAIL,
        phone=None,
    )
    u.set_password(secrets.token_urlsafe(24))
    db.session.add(u)
    db.session.flush()
    return u


def _fetch_b24_user_names(b24_ids: list[str]) -> dict[str, str | None]:
    """Батчем через B24 batch (50 команд за раз): для каждого ID вызываем user.get,
    возвращаем {id_str: full_name или None если не нашёлся}."""
    out: dict[str, str | None] = {}
    for i in range(0, len(b24_ids), 50):
        chunk = b24_ids[i:i + 50]
        cmds = {}
        for uid in chunk:
            cmds[f'u{uid}'] = ('user.get', {'ID': uid})
        try:
            res = _b24_batch(cmds)
        except Exception as e:
            print(f'    user.get batch @{i} FAIL: {e}', flush=True)
            for uid in chunk:
                out[uid] = None
            continue
        for uid in chunk:
            data = res.get(f'u{uid}') or []
            if isinstance(data, list) and data:
                u = data[0]
                name = ' '.join(filter(None, [u.get('LAST_NAME'), u.get('NAME'), u.get('SECOND_NAME')])).strip()
                if not name:
                    name = u.get('EMAIL') or f'B24 user #{uid}'
                out[uid] = name
            else:
                out[uid] = None
    return out


def _ensure_authors_mapped(
    needed_ids: set[str],
    mapping: dict,
    apply_: bool,
) -> dict[str, int]:
    """
    Для всех `needed_ids` возвращает {b24_id: pospro_user_id}.
    Несмапленных:
      - если имя есть в B24 → СОЗДАЁМ system_user (full_name, email b24_<id>@imported.local)
      - если имени нет → привязываем к служебному «Удалённый пользователь B24»
    """
    print(f'  уникальных авторов для проверки: {len(needed_ids)}', flush=True)
    result: dict[str, int] = {}
    valid_ids = {r[0] for r in db.session.execute(text("SELECT id FROM system_users"))}
    missing: list[str] = []

    for b24_id in needed_ids:
        pid = user_pospro_id(mapping, b24_id, 0)
        if pid and pid in valid_ids:
            result[b24_id] = pid
        else:
            missing.append(b24_id)

    if not missing:
        print(f'  все {len(needed_ids)} авторов уже смаплены', flush=True)
        return result

    print(f'  несмапленных / stale: {len(missing)} — тянем имена из B24…', flush=True)
    names = _fetch_b24_user_names(missing)
    created = 0
    attached_deleted = 0
    deleted_user = None

    for b24_id in missing:
        name = names.get(b24_id)
        if name:
            email = f'b24_{b24_id}@imported.local'
            u = SystemUser.query.filter_by(email=email).first()
            if not u:
                u = SystemUser(full_name=name, email=email)
                u.set_password(secrets.token_urlsafe(24))
                if apply_:
                    db.session.add(u)
                    db.session.flush()
                    created += 1
                else:
                    # dry-run: не можем вернуть id, зафиксируем -1
                    result[b24_id] = -1
                    continue
            result[b24_id] = u.id
        else:
            if deleted_user is None:
                if apply_:
                    deleted_user = _get_or_create_deleted_user()
                    db.session.flush()
                else:
                    deleted_user = type('X', (), {'id': -2})()
            result[b24_id] = deleted_user.id
            attached_deleted += 1

    if apply_:
        db.session.commit()
    print(f'  создано новых SystemUser:  {created}', flush=True)
    print(f'  привязано к "Удалённый":   {attached_deleted}', flush=True)
    return result


# ========================================================================
# Chat rooms (ensure + members)
# ========================================================================

def _ensure_deal_room(deal: Deal) -> ChatRoom:
    room = ChatRoom.query.filter_by(kind='deal', related_deal_id=deal.id).first()
    if not room:
        room = ChatRoom(kind='deal', related_deal_id=deal.id)
        db.session.add(room)
        db.session.flush()
    existing = {m.user_id for m in ChatMember.query.filter_by(room_id=room.id)}
    allowed = set()
    if deal.creator_id: allowed.add(deal.creator_id)
    if deal.responsible_user_id: allowed.add(deal.responsible_user_id)
    for m in DealMember.query.filter_by(deal_id=deal.id).all():
        allowed.add(m.user_id)
    for uid in allowed - existing:
        db.session.add(ChatMember(room_id=room.id, user_id=uid))
    return room


def _ensure_task_room(task: Task) -> ChatRoom:
    room = ChatRoom.query.filter_by(kind='task', related_task_id=task.id).first()
    if not room:
        room = ChatRoom(kind='task', related_task_id=task.id)
        db.session.add(room)
        db.session.flush()
    existing = {m.user_id for m in ChatMember.query.filter_by(room_id=room.id)}
    allowed = set()
    if task.creator_id: allowed.add(task.creator_id)
    if task.responsible_id: allowed.add(task.responsible_id)
    for m in TaskMember.query.filter_by(task_id=task.id).all():
        allowed.add(m.user_id)
    for uid in allowed - existing:
        db.session.add(ChatMember(room_id=room.id, user_id=uid))
    return room


def _ensure_member(room_id: int, user_id: int):
    if not user_id:
        return
    if ChatMember.query.filter_by(room_id=room_id, user_id=user_id).first():
        return
    db.session.add(ChatMember(room_id=room_id, user_id=user_id))


# ========================================================================
# Date parsing
# ========================================================================

def _parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace('Z', '+00:00'))
    except Exception:
        return None


# ========================================================================
# File storage
# ========================================================================

def _save_file(entity_type: str, entity_id: int, name: str, data: bytes) -> str:
    import re, unicodedata
    safe = unicodedata.normalize('NFKD', name)
    safe = re.sub(r'[/\\?%*:|"<>]', '_', safe).strip() or 'file'
    ts = int(time.time() * 1000)
    disk_name = f'{ts}_{safe}'
    root = app.config['UPLOAD_FOLDER']
    folder = os.path.join(root, ATTACHMENTS_SUBFOLDER, entity_type, str(entity_id))
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, disk_name), 'wb') as f:
        f.write(data)
    return f'/uploads/{ATTACHMENTS_SUBFOLDER}/{entity_type}/{entity_id}/{disk_name}'


def _choose_uploader(entity, valid_ids: set[int]) -> int | None:
    """Берём creator entity если валиден, иначе NULL."""
    cid = getattr(entity, 'creator_id', None)
    if cid and cid in valid_ids:
        return cid
    return None


# ========================================================================
# PHASE A: deal comments
# ========================================================================

def _phase_a_deal_comments(args, mapping, valid_ids):
    print('\n=== PHASE A: комментарии сделок ===', flush=True)
    rows = db.session.execute(text("""
        SELECT b24_id, pospro_id FROM b24_mirror
         WHERE entity_type='deal'
         ORDER BY CAST(b24_id AS INTEGER) DESC
    """)).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f'  сделок: {len(rows)}', flush=True)

    # 1. Сначала собираем ВСЕ комменты через batch'и → собираем union авторов
    print('  собираем комменты и уникальных авторов…', flush=True)
    all_comments: list[tuple[int, dict]] = []  # (pospro_deal_id, comment_dict)
    authors: set[str] = set()
    t0 = time.time()
    for i in range(0, len(rows), args.batch):
        chunk = rows[i:i + args.batch]
        cmds = {}
        for r in chunk:
            cmds[f'd{r.b24_id}'] = ('crm.timeline.comment.list', {
                'order[ID]': 'ASC',
                'filter[ENTITY_ID]': r.b24_id,
                'filter[ENTITY_TYPE]': 'deal',
                'start': 0,
            })
        try:
            res = _b24_batch(cmds)
        except Exception as e:
            print(f'    batch @{i} FAIL: {e}', flush=True)
            continue
        for r in chunk:
            lst = res.get(f'd{r.b24_id}') or []
            if not isinstance(lst, list):
                continue
            for c in lst:
                all_comments.append((r.pospro_id, c))
                a = str(c.get('AUTHOR_ID') or '')
                if a: authors.add(a)
        if (i // args.batch) % 10 == 0:
            dt = time.time() - t0
            print(f'    …{i + len(chunk)}/{len(rows)}  comments_so_far={len(all_comments)} ({dt:.1f}s)',
                  flush=True)

    print(f'  всего комментов: {len(all_comments)}', flush=True)

    author_map = _ensure_authors_mapped(authors, mapping, args.apply)

    # 2. Вставляем ChatMessage
    print('  создаю ChatMessage…', flush=True)
    n_added = 0; n_skipped = 0
    rooms: dict[int, int] = {}  # pospro_deal_id → room_id
    for i, (pid, c) in enumerate(all_comments):
        b24_cid = str(c.get('ID'))
        if mirror_get('chat_msg', b24_cid):
            n_skipped += 1
            continue
        deal = Deal.query.get(pid)
        if not deal:
            n_skipped += 1
            continue
        if pid not in rooms:
            if args.apply:
                room = _ensure_deal_room(deal)
                db.session.flush()
                rooms[pid] = room.id
            else:
                rooms[pid] = -1
        room_id = rooms[pid]
        author_b24 = str(c.get('AUTHOR_ID') or '')
        author_pid = author_map.get(author_b24)
        if not author_pid or author_pid < 0:
            n_skipped += 1
            continue
        text_body = c.get('COMMENT') or ''
        created_at = _parse_dt(c.get('CREATED')) or datetime.utcnow()
        if args.apply:
            _ensure_member(room_id, author_pid)
            msg = ChatMessage(
                room_id=room_id, author_id=author_pid,
                text=text_body, created_at=created_at,
            )
            db.session.add(msg)
            db.session.flush()
            mirror_set('chat_msg', b24_cid, msg.id)
        n_added += 1
        if args.apply and n_added % 100 == 0:
            db.session.commit()
    if args.apply:
        db.session.commit()
    print(f'  ChatMessage добавлено: {n_added}  пропущено: {n_skipped}', flush=True)


# ========================================================================
# PHASE B: task comments
# ========================================================================

def _phase_b_task_comments(args, mapping, valid_ids):
    print('\n=== PHASE B: комментарии задач ===', flush=True)
    rows = db.session.execute(text("""
        SELECT b24_id, pospro_id FROM b24_mirror
         WHERE entity_type='task'
         ORDER BY CAST(b24_id AS INTEGER) DESC
    """)).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f'  задач: {len(rows)}', flush=True)

    print('  собираем комменты и уникальных авторов…', flush=True)
    all_comments: list[tuple[int, dict]] = []
    authors: set[str] = set()
    t0 = time.time()
    for i in range(0, len(rows), args.batch):
        chunk = rows[i:i + args.batch]
        cmds = {}
        for r in chunk:
            cmds[f't{r.b24_id}'] = ('task.commentitem.getlist', {
                'TASKID': r.b24_id,
                'ORDER[ID]': 'ASC',
            })
        try:
            res = _b24_batch(cmds)
        except Exception as e:
            print(f'    batch @{i} FAIL: {e}', flush=True)
            continue
        for r in chunk:
            lst = res.get(f't{r.b24_id}') or []
            if not isinstance(lst, list):
                continue
            for c in lst:
                all_comments.append((r.pospro_id, c))
                a = str(c.get('AUTHOR_ID') or '')
                if a: authors.add(a)
        if (i // args.batch) % 10 == 0:
            dt = time.time() - t0
            print(f'    …{i + len(chunk)}/{len(rows)}  comments_so_far={len(all_comments)} ({dt:.1f}s)',
                  flush=True)

    print(f'  всего комментов: {len(all_comments)}', flush=True)

    author_map = _ensure_authors_mapped(authors, mapping, args.apply)

    print('  создаю ChatMessage…', flush=True)
    n_added = 0; n_skipped = 0
    rooms: dict[int, int] = {}
    for i, (pid, c) in enumerate(all_comments):
        b24_cid = f't{c.get("ID")}'  # префикс чтобы не пересечься с deal comments
        if mirror_get('chat_msg', b24_cid):
            n_skipped += 1
            continue
        task = Task.query.get(pid)
        if not task:
            n_skipped += 1
            continue
        if pid not in rooms:
            if args.apply:
                room = _ensure_task_room(task)
                db.session.flush()
                rooms[pid] = room.id
            else:
                rooms[pid] = -1
        room_id = rooms[pid]
        author_b24 = str(c.get('AUTHOR_ID') or '')
        author_pid = author_map.get(author_b24)
        if not author_pid or author_pid < 0:
            n_skipped += 1
            continue
        text_body = c.get('POST_MESSAGE') or c.get('MESSAGE') or ''
        created_at = _parse_dt(c.get('POST_DATE')) or _parse_dt(c.get('ADD_DATE')) or datetime.utcnow()
        if args.apply:
            _ensure_member(room_id, author_pid)
            msg = ChatMessage(
                room_id=room_id, author_id=author_pid,
                text=text_body, created_at=created_at,
            )
            db.session.add(msg)
            db.session.flush()
            mirror_set('chat_msg', b24_cid, msg.id)
        n_added += 1
        if args.apply and n_added % 100 == 0:
            db.session.commit()
    if args.apply:
        db.session.commit()
    print(f'  ChatMessage добавлено: {n_added}  пропущено: {n_skipped}', flush=True)


# ========================================================================
# PHASE C: task files
# ========================================================================

def _phase_c_task_files(args, mapping, valid_ids):
    print('\n=== PHASE C: файлы задач ===', flush=True)
    rows = db.session.execute(text("""
        SELECT b24_id, pospro_id FROM b24_mirror
         WHERE entity_type='task'
         ORDER BY CAST(b24_id AS INTEGER) DESC
    """)).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f'  задач: {len(rows)}', flush=True)

    # Батчем забираем task.item.getdata (там UF_TASK_WEBDAV_FILES)
    print('  собираем файлы…', flush=True)
    all_files: list[tuple[int, int, dict]] = []  # (task_pospro_id, b24_task_id, file_dict)
    t0 = time.time()
    for i in range(0, len(rows), args.batch):
        chunk = rows[i:i + args.batch]
        cmds = {r.b24_id: ('task.item.getdata', {'ID': r.b24_id}) for r in chunk}
        try:
            res = _b24_batch(cmds)
        except Exception as e:
            print(f'    batch @{i} FAIL: {e}', flush=True)
            continue
        for r in chunk:
            data = res.get(r.b24_id) or {}
            files = data.get('UF_TASK_WEBDAV_FILES') if isinstance(data, dict) else []
            if not isinstance(files, list):
                continue
            for f in files:
                all_files.append((r.pospro_id, r.b24_id, f))
        if (i // args.batch) % 10 == 0:
            dt = time.time() - t0
            print(f'    …{i + len(chunk)}/{len(rows)}  files_so_far={len(all_files)} ({dt:.1f}s)',
                  flush=True)

    print(f'  всего файлов задач: {len(all_files)}', flush=True)

    n_added = 0; n_skipped = 0; n_fail = 0
    for pid, b24_tid, f in all_files:
        aid = str(f.get('ATTACHMENT_ID') or '')
        if not aid:
            n_skipped += 1
            continue
        if mirror_get('task_file', aid):
            n_skipped += 1
            continue
        task = Task.query.get(pid)
        if not task:
            n_skipped += 1
            continue
        name = f.get('NAME') or f'file_{aid}'
        download_url = f.get('DOWNLOAD_URL')
        if not download_url:
            n_skipped += 1
            continue
        if not args.apply:
            n_added += 1
            continue
        try:
            payload = _download_b24(download_url)
        except Exception as e:
            print(f'    file#{aid} ({name!r}) DL FAIL: {e}', flush=True)
            n_fail += 1
            continue
        file_url = _save_file('task', task.id, name, payload)
        mime, _ = mimetypes.guess_type(name)
        ea = EntityAttachment(
            entity_type='task', entity_id=task.id,
            file_url=file_url, file_name=name,
            file_size=len(payload), mime_type=mime,
            uploaded_by=_choose_uploader(task, valid_ids),
            uploaded_at=datetime.utcnow(),
        )
        db.session.add(ea)
        db.session.flush()
        mirror_set('task_file', aid, ea.id)
        n_added += 1
        if n_added % 20 == 0:
            db.session.commit()
            print(f'    …saved {n_added}', flush=True)
    if args.apply:
        db.session.commit()
    print(f'  EntityAttachment добавлено: {n_added}  пропущено: {n_skipped}  FAIL: {n_fail}',
          flush=True)


# ========================================================================
# PHASE D: deal files
# ========================================================================

def _phase_d_deal_files(args, mapping, valid_ids):
    print('\n=== PHASE D: файлы сделок ===', flush=True)
    # Собираем все UF-file поля сделки
    r = call('crm.deal.userfield.list', {'filter[USER_TYPE_ID]': 'file'})
    file_uf_fields = [u.get('FIELD_NAME') for u in (r.get('result') or []) if u.get('FIELD_NAME')]
    print(f'  file-UF полей: {len(file_uf_fields)}', flush=True)

    rows = db.session.execute(text("""
        SELECT b24_id, pospro_id FROM b24_mirror
         WHERE entity_type='deal'
         ORDER BY CAST(b24_id AS INTEGER) DESC
    """)).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f'  сделок: {len(rows)}', flush=True)

    # Батчем забираем crm.deal.get только нужные UF-поля
    print('  собираем файлы…', flush=True)
    all_files: list[tuple[int, str, str, str]] = []
    # (pospro_deal_id, uf_field, b24_file_id (строка), DOWNLOAD_URL)
    # На deal.get приходит в поле uf_field либо число (ID disk-файла), либо
    # список. Нужно отдельным get-ом вытащить download-url — но для UF file
    # можно использовать disk.file.get(id) → DOWNLOAD_URL.
    # Для простоты: берём как есть; скачивание файлов deal — отдельным циклом.
    t0 = time.time()
    for i in range(0, len(rows), args.batch):
        chunk = rows[i:i + args.batch]
        cmds = {r.b24_id: ('crm.deal.get', {'id': r.b24_id}) for r in chunk}
        try:
            res = _b24_batch(cmds)
        except Exception as e:
            print(f'    batch @{i} FAIL: {e}', flush=True)
            continue
        for r in chunk:
            d = res.get(r.b24_id) or {}
            if not isinstance(d, dict):
                continue
            for uf in file_uf_fields:
                v = d.get(uf)
                if not v or v in ('0', 0, '', []):
                    continue
                if isinstance(v, list):
                    for item in v:
                        if item and item not in ('0', 0, ''):
                            all_files.append((r.pospro_id, uf, str(item), ''))
                else:
                    all_files.append((r.pospro_id, uf, str(v), ''))
        if (i // args.batch) % 10 == 0:
            dt = time.time() - t0
            print(f'    …{i + len(chunk)}/{len(rows)}  files_so_far={len(all_files)} ({dt:.1f}s)',
                  flush=True)

    print(f'  всего файл-записей на сделках: {len(all_files)}', flush=True)

    # Для deal UF-file: v — это disk file id, нужно через disk.attachedObject.get
    # или через crm.item.get разворачивать. Это требует дополнительных вызовов.
    # Делаем batch'ами disk.attachedObject.get(id=X) → DOWNLOAD_URL.
    unique_file_ids = list({x[2] for x in all_files})
    print(f'  уникальных file_id: {len(unique_file_ids)}', flush=True)
    disk_meta: dict[str, dict] = {}
    for i in range(0, len(unique_file_ids), 50):
        chunk = unique_file_ids[i:i + 50]
        cmds = {f'f{fid}': ('disk.attachedObject.get', {'id': fid}) for fid in chunk}
        try:
            res = _b24_batch(cmds)
        except Exception as e:
            print(f'    disk.attachedObject batch @{i} FAIL: {e}', flush=True)
            continue
        for fid in chunk:
            d = res.get(f'f{fid}') or {}
            if isinstance(d, dict) and d.get('DOWNLOAD_URL'):
                disk_meta[fid] = d

    print(f'  с DOWNLOAD_URL получено: {len(disk_meta)}', flush=True)

    n_added = 0; n_skipped = 0; n_fail = 0
    for pid, uf, fid, _ in all_files:
        meta_key = f'deal_file_{fid}_{uf}_{pid}'
        if mirror_get('deal_file', meta_key):
            n_skipped += 1
            continue
        meta = disk_meta.get(fid)
        if not meta:
            n_skipped += 1
            continue
        deal = Deal.query.get(pid)
        if not deal:
            n_skipped += 1
            continue
        name = meta.get('NAME') or f'file_{fid}'
        download_url = meta.get('DOWNLOAD_URL')
        if not args.apply:
            n_added += 1
            continue
        try:
            payload = _download_b24(download_url)
        except Exception as e:
            print(f'    file#{fid} ({name!r}) DL FAIL: {e}', flush=True)
            n_fail += 1
            continue
        file_url = _save_file('deal', deal.id, name, payload)
        mime, _ = mimetypes.guess_type(name)
        ea = EntityAttachment(
            entity_type='deal', entity_id=deal.id,
            file_url=file_url, file_name=name,
            file_size=len(payload), mime_type=mime,
            uploaded_by=_choose_uploader(deal, valid_ids),
            uploaded_at=datetime.utcnow(),
        )
        db.session.add(ea)
        db.session.flush()
        mirror_set('deal_file', meta_key, ea.id)
        n_added += 1
        if n_added % 20 == 0:
            db.session.commit()
            print(f'    …saved {n_added}', flush=True)
    if args.apply:
        db.session.commit()
    print(f'  EntityAttachment добавлено: {n_added}  пропущено: {n_skipped}  FAIL: {n_fail}',
          flush=True)


# ========================================================================
# Main
# ========================================================================

def main() -> int:
    args = _parse_args()
    with app.app_context():
        mapping = load_mapping()
        valid_ids = {r[0] for r in db.session.execute(text("SELECT id FROM system_users"))}
        print(f'mode={"APPLY" if args.apply else "DRY-RUN"}  phase={args.phase}  '
              f'limit={args.limit or "all"}', flush=True)
        print(f'  system_users count: {len(valid_ids)}', flush=True)

        if args.phase in ('A', 'all'):
            _phase_a_deal_comments(args, mapping, valid_ids)
            # После A могли создаться новые юзеры — обновим valid_ids
            valid_ids = {r[0] for r in db.session.execute(text("SELECT id FROM system_users"))}
        if args.phase in ('B', 'all'):
            _phase_b_task_comments(args, mapping, valid_ids)
            valid_ids = {r[0] for r in db.session.execute(text("SELECT id FROM system_users"))}
        if args.phase in ('C', 'all'):
            _phase_c_task_files(args, mapping, valid_ids)
        if args.phase in ('D', 'all'):
            _phase_d_deal_files(args, mapping, valid_ids)
    return 0


if __name__ == '__main__':
    sys.exit(main())
