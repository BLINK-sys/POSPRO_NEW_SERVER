"""
Diag: вытаскивает список рабочих групп (проектов) из B24 через
`sonet_group.get`. Нужно увидеть как они устроены и что из них есть
смысл перенести в наш модуль «Проекты».

Печатает: ID, NAME, DESCRIPTION, OPENED, VISIBLE, CLOSED, DATE_CREATE,
NUMBER_OF_MEMBERS, ACTIVITY_DATE, OWNER_ID, PROJECT (флаг «это проект
а не группа»).

Запуск: python -u -m migrations.b24_projects_diag
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

from migrations.bitrix24._b24 import call


def _fetch_all() -> list[dict]:
    """
    sonet_group.get — обычный start-пагинируемый метод. Берём все
    группы, включая закрытые (CLOSED=Y) и архивные (ACTIVE=N),
    чтобы было видно полное хозяйство.
    """
    groups: list[dict] = []
    start = 0
    while True:
        out = call('sonet_group.get', {
            'ORDER[ID]': 'ASC',
            'start': start,
        })
        batch = out.get('result') or []
        if isinstance(batch, dict):
            # у некоторых вебхуков результат — dict id→group
            batch = list(batch.values())
        if not batch:
            break
        groups.extend(batch)
        nxt = out.get('next')
        if nxt is None:
            break
        start = int(nxt)
    return groups


def main() -> int:
    with app.app_context():
        print('Fetching sonet_group.get …', flush=True)
        try:
            groups = _fetch_all()
        except Exception as e:
            print(f'ERROR: {e}', flush=True)
            return 1

        print(f'\nTOTAL groups: {len(groups)}', flush=True)

        # Короткая таблица по основным полям.
        active = [g for g in groups if str(g.get('CLOSED', 'N')).upper() != 'Y']
        projects = [g for g in groups if str(g.get('PROJECT', 'N')).upper() == 'Y']
        print(f'  CLOSED=N (активные):     {len(active)}', flush=True)
        print(f'  PROJECT=Y (проект-флаг): {len(projects)}', flush=True)

        print('\n--- ПЕРВЫЕ 50 (ID, NAME, CLOSED, PROJECT, OWNER_ID, DATE_CREATE) ---', flush=True)
        for g in groups[:50]:
            print(
                f"  #{g.get('ID'):<5} | "
                f"closed={str(g.get('CLOSED','N')):<1} | "
                f"project={str(g.get('PROJECT','N')):<1} | "
                f"owner=#{g.get('OWNER_ID') or '-':<5} | "
                f"{g.get('DATE_CREATE','')} | "
                f"{(g.get('NAME') or '')[:70]!r}",
                flush=True,
            )

        print('\n--- Образец ПОЛНОГО JSON для первой группы ---', flush=True)
        if groups:
            import json
            print(json.dumps(groups[0], ensure_ascii=False, indent=2), flush=True)

    return 0


if __name__ == '__main__':
    sys.exit(main())
