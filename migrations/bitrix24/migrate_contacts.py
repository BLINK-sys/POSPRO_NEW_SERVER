"""
Миграция контактов Б24 → `kp_client`.

- Дедуп по normalized phone/email: если такой контакт уже есть в
  kp_client — не создаём, ссылаем в b24_mirror на существующий (ВАЖНО
  для последующей migrate_deals, где по contact_id Б24 должен найтись
  pospro-client).
- Привязка к компании — через b24_mirror('company', COMPANY_ID).
- Автор — через user_map (ASSIGNED_BY_ID → system_users).

CLI:
  python -u -m migrations.bitrix24.migrate_contacts [--limit N] [--dry-run]
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import app
from extensions import db
from sqlalchemy import func as sqlfunc, cast
from sqlalchemy.types import Text

from models.systemuser import SystemUser
from models.kp_client import KpClient

from migrations.bitrix24._b24 import iter_list
from migrations.bitrix24._utils import (
    load_mapping, user_pospro_id,
    normalize_phone, phone_digits,
    mirror_get, mirror_set,
)


FIELDS = [
    'ID', 'NAME', 'LAST_NAME', 'SECOND_NAME',
    'PHONE', 'EMAIL', 'COMPANY_ID',
    'COMMENTS', 'ASSIGNED_BY_ID', 'DATE_CREATE',
]


def _collect_contacts(co: dict) -> list[dict]:
    """
    Собирает список {phone, note} для kp_client.contacts из PHONE/EMAIL
    массивов Б24. Телефоны нормализуются; тип (WORK/HOME/MOBILE) идёт в note.
    Emails тоже идут отдельными записями (phone='', note='email: ...') —
    т.к. kp_client.contacts хранит только phone+note, email попадёт в
    поле note как 'email: ...'. Это компромисс чтобы ничего не потерять.
    """
    out: list[dict] = []
    for p in co.get('PHONE') or []:
        raw = (p.get('VALUE') or '').strip()
        if not raw:
            continue
        phone = normalize_phone(raw)
        if not phone:
            continue
        vtype = (p.get('VALUE_TYPE') or '').strip()
        note = vtype if vtype and vtype.lower() not in ('work', 'other') else ''
        out.append({'phone': phone, 'note': note})
    for e in co.get('EMAIL') or []:
        raw = (e.get('VALUE') or '').strip()
        if not raw:
            continue
        # Храним email тоже в contacts, в поле phone (чтобы было видно в
        # UI) с пометкой «email» в note.
        out.append({'phone': raw, 'note': f'email'})
    return out


def _find_existing_by_phone_or_email(contacts: list[dict]) -> KpClient | None:
    """
    Дедуп: ищем kp_client где contacts JSONB содержит ЛЮБОЙ из наших
    телефонов (сравниваем по digits) или email.
    """
    for c in contacts:
        phone = c.get('phone') or ''
        if not phone:
            continue
        # Сравниваем через cast JSONB к text и LIKE по цифрам — грубо, но
        # для миграции ОК. При больших таблицах можно добавить GIN-индекс.
        if c.get('note') == 'email':
            key = phone.lower()
            like = f'%{key}%'
            row = KpClient.query.filter(
                sqlfunc.lower(cast(KpClient.contacts, Text)).like(like)
            ).first()
            if row:
                return row
        else:
            digits = phone_digits(phone)
            if len(digits) < 7:
                continue
            # Берём последние 10 цифр (без кода страны) чтобы матчить и
            # +7..., и 8..., и без префикса.
            tail = digits[-10:]
            like = f'%{tail}%'
            row = KpClient.query.filter(
                sqlfunc.cast(KpClient.contacts, Text).like(like)
            ).first()
            if row:
                return row
    return None


def _full_name(co: dict) -> str:
    parts = [
        (co.get('LAST_NAME') or '').strip(),
        (co.get('NAME') or '').strip(),
        (co.get('SECOND_NAME') or '').strip(),
    ]
    name = ' '.join(p for p in parts if p).strip()
    return name or f'B24 contact #{co["ID"]}'


def migrate_one(co: dict, mapping: dict, owner_id: int, dry_run: bool) -> str:
    b24_id = co['ID']
    existing_pid = mirror_get('contact', b24_id)
    if existing_pid:
        return f'skip (already imported → pospro #{existing_pid})'

    name = _full_name(co)
    contacts = _collect_contacts(co)
    note = (co.get('COMMENTS') or '').strip() or None
    created_by = user_pospro_id(mapping, co.get('ASSIGNED_BY_ID'), owner_id)
    company_b24 = co.get('COMPANY_ID')
    company_pid = mirror_get('company', company_b24) if company_b24 and company_b24 != '0' else None

    # Дедуп по phone/email.
    existing = _find_existing_by_phone_or_email(contacts)
    if existing:
        if dry_run:
            return f'[dry-run] dedup → existing #{existing.id} {existing.full_name!r}'
        mirror_set('contact', b24_id, existing.id)
        return f'dedup → existing #{existing.id} {existing.full_name!r}'

    if dry_run:
        return (f'[dry-run] would create: {name!r} '
                f'contacts={len(contacts)} company_pid={company_pid} by #{created_by}')

    c = KpClient(
        full_name=name[:255],
        object=(note[:1024] if note else None),
        contacts=contacts,
        company_id=company_pid,
        created_by=created_by,
    )
    db.session.add(c)
    db.session.flush()
    mirror_set('contact', b24_id, c.id)
    return f'created #{c.id} {name!r} (contacts={len(contacts)})'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    print(f'=== migrate_contacts  limit={args.limit or "ALL"}  dry_run={args.dry_run} ===',
          flush=True)

    with app.app_context():
        mapping = load_mapping()
        owner = SystemUser.query.filter_by(is_owner=True).first()
        owner_id = owner.id

        n_total = n_created = n_dedup = n_skipped = 0
        for co in iter_list('crm.contact.list', {
            'select[]': FIELDS,
            'order[DATE_CREATE]': 'ASC',
        }):
            n_total += 1
            result = migrate_one(co, mapping, owner_id, args.dry_run)
            if result.startswith('skip'):
                n_skipped += 1
            elif 'dedup' in result:
                n_dedup += 1
            elif 'created' in result or 'would create' in result:
                n_created += 1
            if n_total <= 20 or n_total % 200 == 0:
                print(f'  [{n_total:5d}] b24#{co["ID"]:>7}  {result}', flush=True)
            if args.limit and n_total >= args.limit:
                break
            if not args.dry_run and n_total % 50 == 0:
                db.session.commit()

        if not args.dry_run:
            db.session.commit()

        print(f'\n=== TOTALS ===', flush=True)
        print(f'  processed: {n_total}', flush=True)
        print(f'  created:   {n_created}', flush=True)
        print(f'  dedup:     {n_dedup}', flush=True)
        print(f'  skipped:   {n_skipped}', flush=True)


if __name__ == '__main__':
    main()
