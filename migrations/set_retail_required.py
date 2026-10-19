"""
Простановка required_dict_codes на стадии воронки «Розница».

Политика (по словам пользователя):
  - первые 2 стадии (по order_pos) — пусто (никаких обязательных полей);
  - все остальные — все 4 словаря опросника:
      ['heat', 'city', 'activity', 'business_type'].

Dry-run по умолчанию.

Запуск:
    python -u -m migrations.set_retail_required
    python -u -m migrations.set_retail_required --apply
    python -u -m migrations.set_retail_required --pipeline-id 2 --apply
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db

from models.deal_pipeline import DealPipeline, DealStage


REQUIRED_CODES = ['heat', 'city', 'activity', 'business_type']


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--pipeline-id', type=int, default=None,
                   help='Если задан — обрабатываем именно эту воронку, '
                        'без поиска по имени.')
    return p.parse_args()


def _find_retail_pipeline() -> DealPipeline | None:
    # Пробуем точные/частичные имена.
    for q in ('Розница', 'Розничные продажи', 'Розничные'):
        p = DealPipeline.query.filter(
            db.func.lower(DealPipeline.name) == q.lower(),
        ).first()
        if p:
            return p
    # Фолбэк — любой pipeline, в имени которого встречается «розни».
    p = DealPipeline.query.filter(
        db.func.lower(DealPipeline.name).like('%розни%'),
    ).order_by(DealPipeline.id.asc()).first()
    return p


def main() -> int:
    args = _parse_args()
    with app.app_context():
        if args.pipeline_id is not None:
            pipeline = DealPipeline.query.get(args.pipeline_id)
            if not pipeline:
                print(f'Воронка id={args.pipeline_id} не найдена.', flush=True)
                return 1
        else:
            pipeline = _find_retail_pipeline()
            if not pipeline:
                print('Воронка «Розница» не найдена по имени. '
                      'Передай --pipeline-id вручную. Список воронок:',
                      flush=True)
                for p in DealPipeline.query.order_by(DealPipeline.id).all():
                    print(f'  id={p.id}  name={p.name!r}', flush=True)
                return 1

        print(f'=== pipeline id={pipeline.id}  name={pipeline.name!r}  '
              f'mode={"APPLY" if args.apply else "DRY-RUN"}', flush=True)

        stages = DealStage.query.filter_by(pipeline_id=pipeline.id)\
            .order_by(DealStage.order.asc(), DealStage.id.asc()).all()
        print(f'стадий: {len(stages)}', flush=True)
        print('', flush=True)

        n_changed = 0
        for i, s in enumerate(stages):
            want = [] if i < 2 else list(REQUIRED_CODES)
            have = list(s.required_dict_codes or [])
            # Сравнение set — порядок не важен.
            if set(have) == set(want):
                status = 'ok'
            else:
                status = f'CHANGE  {have} → {want}'
                n_changed += 1
                if args.apply:
                    s.required_dict_codes = want
            print(f'  [{i:>2}] order={s.order:<4} id={s.id:<5} '
                  f'{s.name!r:<40} {status}', flush=True)

        if args.apply and n_changed:
            db.session.commit()
            print('', flush=True)
            print(f'OK, обновлено {n_changed} стадий.', flush=True)
        elif not args.apply:
            print('', flush=True)
            print(f'DRY-RUN: будет обновлено {n_changed} стадий. '
                  '--apply для реальной записи.', flush=True)
        else:
            print('', flush=True)
            print('Нечего менять, всё уже совпадает.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
