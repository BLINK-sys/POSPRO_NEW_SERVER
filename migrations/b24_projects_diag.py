"""
Diag: вытаскивает список рабочих групп (проектов) из B24.

Использует ОТДЕЛЬНЫЙ вебхук `B24_WEBHOOK_PROJECTS` (у него скоуп
`socialnetwork`), чтобы не трогать основной `B24_WEBHOOK` с другим
набором прав.

Запуск: python -u -m migrations.b24_projects_diag
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests


HTTP_TIMEOUT = (15, 60)


def _webhook_base() -> str:
    url = os.environ.get('B24_WEBHOOK_PROJECTS', '').rstrip('/')
    if not url:
        raise RuntimeError(
            'B24_WEBHOOK_PROJECTS env var is not set. '
            'Нужен отдельный вебхук с правом socialnetwork.'
        )
    return url


def _call(method: str, params: dict | None = None) -> dict:
    url = f'{_webhook_base()}/{method}.json'
    r = requests.post(url, json=params or {}, timeout=HTTP_TIMEOUT)
    body = r.text
    if r.status_code != 200:
        raise RuntimeError(f'{method} HTTP {r.status_code}: {body[:400]}')
    return r.json()


def _fetch_all_groups() -> list[dict]:
    """
    sonet_group.get — start-пагинируемый. Берём ВСЕ группы, включая
    закрытые (CLOSED=Y), чтобы было видно полное хозяйство.
    """
    groups: list[dict] = []
    start = 0
    while True:
        out = _call('sonet_group.get', {
            'ORDER[ID]': 'ASC',
            'start': start,
        })
        batch = out.get('result') or []
        if isinstance(batch, dict):
            batch = list(batch.values())
        if not batch:
            break
        groups.extend(batch)
        nxt = out.get('next')
        if nxt is None:
            break
        start = int(nxt)
        if start > 100_000:  # защита от бесконечного цикла
            break
    return groups


def main() -> int:
    print('Fetching sonet_group.get via B24_WEBHOOK_PROJECTS …', flush=True)
    try:
        groups = _fetch_all_groups()
    except Exception as e:
        print(f'ERROR: {e}', flush=True)
        return 1

    total = len(groups)
    print(f'\nTOTAL groups: {total}', flush=True)
    active = [g for g in groups if str(g.get('CLOSED', 'N')).upper() != 'Y']
    projects = [g for g in groups if str(g.get('PROJECT', 'N')).upper() == 'Y']
    print(f'  CLOSED=N (активные):     {len(active)}', flush=True)
    print(f'  PROJECT=Y (проект-флаг): {len(projects)}', flush=True)

    print('\n--- ПЕРВЫЕ 100 (ID | closed | project | owner | date | NAME) ---',
          flush=True)
    for g in groups[:100]:
        print(
            f"  #{str(g.get('ID')):<5} | "
            f"closed={str(g.get('CLOSED','N')):<1} | "
            f"project={str(g.get('PROJECT','N')):<1} | "
            f"owner=#{str(g.get('OWNER_ID') or '-'):<5} | "
            f"{str(g.get('DATE_CREATE',''))[:16]:<16} | "
            f"{(g.get('NAME') or '')[:80]}",
            flush=True,
        )

    print('\n--- Образец ПОЛНОГО JSON для первой группы ---', flush=True)
    if groups:
        print(json.dumps(groups[0], ensure_ascii=False, indent=2), flush=True)

    return 0


if __name__ == '__main__':
    sys.exit(main())
