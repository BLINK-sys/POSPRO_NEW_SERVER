"""
Простановка цвета всем DealSource, у которых color пустой или дефолтно-серый
(#94a3b8 / #e5e7eb). Такое бывает у «новых» источников — созданных авто-
импортом или UF-резолвером, без цвета. На канбане они все серые и слипаются.

Назначаем по кругу из палитры (та же, что в pipelines-manager), пропуская
цвета, которые уже заняты существующими цветными источниками — чтобы не
дублировать.

Dry-run по умолчанию.

Запуск:
    python -u -m migrations.recolor_deal_sources
    python -u -m migrations.recolor_deal_sources --apply
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db

from models.deal_source import DealSource


PALETTE = [
    '#ef4444',  # red
    '#fb7185',  # rose
    '#f97316',  # orange
    '#f59e0b',  # amber
    '#eab308',  # yellow
    '#facc15',  # yellow-400
    '#84cc16',  # lime
    '#22c55e',  # green
    '#10b981',  # emerald
    '#14b8a6',  # teal
    '#06b6d4',  # cyan
    '#0ea5e9',  # sky
    '#3b82f6',  # blue
    '#6366f1',  # indigo
    '#8b5cf6',  # violet
    '#a855f7',  # purple
    '#d946ef',  # fuchsia
    '#ec4899',  # pink
]

GREY_LIKE = {'', None, '#94a3b8', '#e5e7eb', '#6b7280'}


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    with app.app_context():
        all_src = DealSource.query.order_by(DealSource.id).all()
        greys = [s for s in all_src
                 if (s.color or '').strip().lower() in {
                     c.lower() if c else '' for c in GREY_LIKE
                 }]
        taken = {(s.color or '').strip().lower() for s in all_src
                 if s not in greys and (s.color or '').strip()}

        print(f'=== DealSource recolor  mode={"APPLY" if args.apply else "DRY-RUN"}',
              flush=True)
        print(f'  всего источников: {len(all_src)}', flush=True)
        print(f'  серых/без цвета:  {len(greys)}', flush=True)
        print(f'  уже с цветом:     {len(all_src) - len(greys)}', flush=True)
        print('', flush=True)

        # Пул свободных цветов — палитра минус уже занятые.
        free = [c for c in PALETTE if c.lower() not in taken]
        if not free:
            # Если всю палитру уже разобрали — всё равно крутим по кругу
            # полную палитру (дубли между серыми неизбежны, но не критично).
            free = list(PALETTE)

        pool = list(free)
        n_changed = 0
        for s in greys:
            if not pool:
                pool = list(free)
            new_color = pool.pop(0)
            print(f'  id={s.id:<4} {s.name!r:<40} '
                  f'{s.color!r:<10} → {new_color}', flush=True)
            if args.apply:
                s.color = new_color
            n_changed += 1

        if args.apply and n_changed:
            db.session.commit()
            print('', flush=True)
            print(f'OK, обновлено {n_changed} источников.', flush=True)
        elif not args.apply:
            print('', flush=True)
            print(f'DRY-RUN: будет перекрашено {n_changed}. --apply для реального.',
                  flush=True)
        else:
            print('Нечего перекрашивать.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
