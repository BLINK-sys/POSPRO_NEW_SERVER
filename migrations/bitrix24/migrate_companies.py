"""
Миграция компаний Б24 → `kp_company`.

Идемпотентна через `b24_mirror(entity_type='company')`:
  - перезапуск скрипта не создаёт дублей;
  - если по ID компании Б24 уже есть запись в zrcl'е — пропускаем.

CLI:
  python -u -m migrations.bitrix24.migrate_companies [--limit N] [--dry-run]
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import app
from extensions import db

from models.systemuser import SystemUser
from models.kp_company import KpCompany

from migrations.bitrix24._b24 import iter_list
from migrations.bitrix24._utils import (
    load_mapping, user_pospro_id,
    normalize_phone, mirror_get, mirror_set,
)


FIELDS = [
    'ID', 'TITLE', 'COMPANY_TYPE', 'INDUSTRY',
    'PHONE', 'EMAIL', 'WEB', 'ADDRESS', 'ADDRESS_CITY', 'ADDRESS_COUNTRY',
    'COMMENTS', 'ASSIGNED_BY_ID', 'DATE_CREATE',
]


def _first_value(items: list[dict] | None) -> str | None:
    """Из массивов phone/email/web Б24 берём первое непустое VALUE."""
    if not items:
        return None
    for it in items:
        v = (it.get('VALUE') or '').strip()
        if v:
            return v
    return None


def _compose_address(co: dict) -> str | None:
    parts = []
    for k in ('ADDRESS_COUNTRY', 'ADDRESS_CITY', 'ADDRESS'):
        v = (co.get(k) or '').strip()
        if v and v not in parts:
            parts.append(v)
    return ', '.join(parts) or None


def migrate_one(co: dict, mapping: dict, owner_id: int, dry_run: bool) -> str:
    b24_id = co['ID']
    existing_pid = mirror_get('company', b24_id)
    if existing_pid:
        return f'skip (already imported → pospro #{existing_pid})'

    phone = normalize_phone(_first_value(co.get('PHONE')))
    email = _first_value(co.get('EMAIL'))
    website = _first_value(co.get('WEB'))
    address = _compose_address(co)
    name = (co.get('TITLE') or '').strip() or f'B24 company #{b24_id}'
    note = (co.get('COMMENTS') or '').strip() or None
    created_by = user_pospro_id(mapping, co.get('ASSIGNED_BY_ID'), owner_id)

    if dry_run:
        return f'[dry-run] would create: {name!r} phone={phone!r} email={email!r} by #{created_by}'

    c = KpCompany(
        name=name[:255],
        phone=phone,
        email=email,
        website=website,
        address=address,
        note=note,
        created_by=created_by,
    )
    db.session.add(c)
    db.session.flush()
    mirror_set('company', b24_id, c.id)
    return f'created #{c.id} {name!r}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0,
                    help='сколько компаний обработать за прогон (0 = все)')
    ap.add_argument('--dry-run', action='store_true',
                    help='только показать что бы сделал, без записи')
    args = ap.parse_args()

    print(f'=== migrate_companies  limit={args.limit or "ALL"}  dry_run={args.dry_run} ===',
          flush=True)

    with app.app_context():
        mapping = load_mapping()
        owner = SystemUser.query.filter_by(is_owner=True).first()
        if not owner:
            print('!! no owner user', flush=True)
            sys.exit(1)
        owner_id = owner.id

        n_total = n_created = n_skipped = 0
        for co in iter_list('crm.company.list', {
            'select[]': FIELDS,
            'order[DATE_CREATE]': 'ASC',
        }):
            n_total += 1
            result = migrate_one(co, mapping, owner_id, args.dry_run)
            if result.startswith('skip'):
                n_skipped += 1
            elif 'created' in result or 'would create' in result:
                n_created += 1
            if n_total <= 20 or n_total % 100 == 0:
                print(f'  [{n_total:5d}] b24#{co["ID"]:>7}  {result}', flush=True)
            if args.limit and n_total >= args.limit:
                break
            # commit пачками по 50, чтобы не держать длинную транзакцию
            if not args.dry_run and n_total % 50 == 0:
                db.session.commit()

        if not args.dry_run:
            db.session.commit()

        print(f'\n=== TOTALS ===', flush=True)
        print(f'  processed: {n_total}', flush=True)
        print(f'  created:   {n_created}', flush=True)
        print(f'  skipped:   {n_skipped}', flush=True)


if __name__ == '__main__':
    main()
