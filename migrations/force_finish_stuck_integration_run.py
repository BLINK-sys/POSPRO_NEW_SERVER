"""
Разовый fix для «подвисшего» IntegrationRun.

Ищет все running-run'ы, которые:
  - длятся более MIN_HOURS часов (явно не нормальная работа);
  - прогресс по products показывает ≥95% (значит фактически выгрузка
    отработала, но финальный STATUS в БД не проставился — воркер упал,
    либо на последнем commit'е connection reset, либо ещё что).

Такие run'ы помечаем succeeded, finished_at=now, error записываем
диагностикой «auto-finished, ...». Активные команды в очереди
(run_now / cancel) чистим, чтобы воркер не поднял «мертвые» задания.

По умолчанию dry-run — только показывает что найдено. С `--apply` пишет.

Запуск через Render Job:
    python -u -m migrations.force_finish_stuck_integration_run
    python -u -m migrations.force_finish_stuck_integration_run --apply
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from models.integration import IntegrationRun, IntegrationCommand


MIN_HOURS = 12         # считаем «застрял» всё что >12 часов в running
MIN_PRODUCTS_RATIO = 0.95  # процент выгруженных товаров для авто-finish
# После этого порога добавляем финализацию в обход ratio: воркер
# обновляет progress через SSE и пишет его в БД только при финише,
# поэтому «висящая» запись старше 3 суток почти всегда означает что
# воркер фактически завершил работу, но crash'нулся на финальном commit.
HARD_HOURS = 72


def _ratio(progress: dict | None) -> float:
    if not isinstance(progress, dict):
        return 0.0
    total = progress.get('products_total') or progress.get('total') or 0
    done = progress.get('products_done') or progress.get('done') or 0
    try:
        total = int(total); done = int(done)
    except (TypeError, ValueError):
        return 0.0
    if total <= 0:
        return 0.0
    return done / total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()

    now = datetime.utcnow()
    cutoff = now - timedelta(hours=MIN_HOURS)

    stuck = (
        IntegrationRun.query
        .filter(IntegrationRun.status == 'running')
        .filter(IntegrationRun.started_at <= cutoff)
        .all()
    )
    print(f'Mode: {"APPLY" if args.apply else "DRY-RUN"}', flush=True)
    print(f'Found {len(stuck)} running runs older than {MIN_HOURS}h', flush=True)

    fixed = 0
    for run in stuck:
        ratio = _ratio(run.progress)
        age_h = (now - run.started_at).total_seconds() / 3600 if run.started_at else 0
        print(
            f'  run #{run.id} type={run.type} started={run.started_at} '
            f'age={age_h:.1f}h phase={run.phase} ratio={ratio:.2%}',
            flush=True,
        )
        is_hard_timeout = age_h >= HARD_HOURS
        if ratio < MIN_PRODUCTS_RATIO and not is_hard_timeout:
            print(f'    SKIP: прогресс <{MIN_PRODUCTS_RATIO:.0%} и возраст <{HARD_HOURS}ч', flush=True)
            continue

        reason = (
            'hard timeout' if is_hard_timeout
            else f'ratio {ratio:.1%}'
        )
        if args.apply:
            run.status = 'succeeded'
            run.finished_at = now
            run.error = (
                f'auto-finished: висел {age_h:.0f}ч в running ({reason})'
            )
            fixed += 1
            print(f'    MARKED succeeded ({reason})', flush=True)
        else:
            print(f'    WOULD mark succeeded ({reason})', flush=True)

        # Чистим недоконсьюмленные команды того же типа — чтобы воркер
        # не поднял cancel/run_now от старого «мертвого» run.
        pending = IntegrationCommand.query.filter_by(
            type=run.type, consumed_at=None,
        ).all()
        for cmd in pending:
            print(f'    pending cmd #{cmd.id} command={cmd.command}', flush=True)
            if args.apply:
                db.session.delete(cmd)

    if args.apply:
        db.session.commit()
        print(f'\nFixed {fixed} runs', flush=True)
    else:
        print('\nDRY-RUN. Re-run with --apply to write.', flush=True)
    return 0


if __name__ == '__main__':
    with app.app_context():
        sys.exit(main())
