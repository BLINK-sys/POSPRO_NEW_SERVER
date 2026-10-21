"""
Разово: очистить BBCode-разметку в ChatMessage.text (пришло из B24
timeline/task-комментариев). Примеры:

  [USER=4615]Антон Боцан[/USER]           → @Антон Боцан
  [URL=/company/..]эффективность[/URL]    → эффективность        (внутр. B24-ссылки)
  [URL=https://ya.ru]Yandex[/URL]         → Yandex (https://ya.ru)
  [B]жирный[/B] / [I]курсив[/I]           → жирный / курсив      (просто текст)
  [COLOR=#ff0000]..[/COLOR]               → ..                   (цвет снимаем)
  [LIST][*]item1[*]item2[/LIST]           → · item1\\n· item2
  [QUOTE]..[/QUOTE] / [CODE]..[/CODE]     → содержимое
  — всё остальное неизвестное [TAG]..[/TAG] → содержимое

Идемпотентно: прогон не вредит уже чистым сообщениям.

Dry-run по умолчанию.

Запуск:
    python -u -m migrations.clean_bbcode_in_chats
    python -u -m migrations.clean_bbcode_in_chats --apply
    python -u -m migrations.clean_bbcode_in_chats --limit 20   # первые 20 c BBCode
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from models.chat import ChatMessage


# ---- regex ---------------------------------------------------------------

# [USER=123]Имя[/USER] → @Имя
RE_USER = re.compile(r'\[USER=\d+\](.*?)\[/USER\]', re.IGNORECASE | re.DOTALL)
# [URL=https://...]text[/URL] — внешняя
RE_URL_EXT = re.compile(
    r'\[URL=(https?://[^\]]+)\](.*?)\[/URL\]', re.IGNORECASE | re.DOTALL
)
# [URL=/path]text[/URL] — внутренняя B24
RE_URL_INT = re.compile(
    r'\[URL=[^\]]+\](.*?)\[/URL\]', re.IGNORECASE | re.DOTALL
)
# [COLOR=#xxx]text[/COLOR]
RE_COLOR = re.compile(
    r'\[COLOR=[^\]]+\](.*?)\[/COLOR\]', re.IGNORECASE | re.DOTALL
)
# [FONT=...]text[/FONT]
RE_FONT = re.compile(
    r'\[FONT=[^\]]+\](.*?)\[/FONT\]', re.IGNORECASE | re.DOTALL
)
# [SIZE=...]text[/SIZE]
RE_SIZE = re.compile(
    r'\[SIZE=[^\]]+\](.*?)\[/SIZE\]', re.IGNORECASE | re.DOTALL
)
# [B]text[/B], [I]text[/I], [U]text[/U], [S]text[/S]
RE_SIMPLE = re.compile(r'\[/?[BIUS]\]', re.IGNORECASE)
# [QUOTE]..[/QUOTE], [CODE]..[/CODE]
RE_QUOTE = re.compile(r'\[/?QUOTE\]', re.IGNORECASE)
RE_CODE = re.compile(r'\[/?CODE\]', re.IGNORECASE)
# [LIST][*]...[*]... → · ...\n· ...
RE_LIST = re.compile(r'\[LIST\](.*?)\[/LIST\]', re.IGNORECASE | re.DOTALL)
RE_LIST_ITEM = re.compile(r'\[\*\]', re.IGNORECASE)
# [IMG]url[/IMG] → url
RE_IMG = re.compile(r'\[IMG\](.*?)\[/IMG\]', re.IGNORECASE | re.DOTALL)
# Все прочие пары [TAG]..[/TAG] → содержимое (жадность разруливает re.sub)
RE_ANY_PAIR = re.compile(
    r'\[([A-Za-z]+)(?:=[^\]]*)?\](.*?)\[/\1\]',
    re.IGNORECASE | re.DOTALL,
)
# Одиночные непарные теги [TAG] или [/TAG] → удалить
RE_LONE = re.compile(r'\[/?[A-Za-z]+(?:=[^\]]*)?\]')
# Множественные пустые строки → одна
RE_MULTI_NL = re.compile(r'\n{3,}')


def _clean_list_block(m: re.Match) -> str:
    inner = m.group(1)
    # [*] заменяем на новую строку с маркером
    items = RE_LIST_ITEM.split(inner)
    items = [i.strip() for i in items if i.strip()]
    return '\n' + '\n'.join(f'· {i}' for i in items) + '\n'


def clean(text: str) -> str:
    if not text or '[' not in text:
        return text
    s = text
    # Специализированные теги — сначала с содержимым
    s = RE_USER.sub(lambda m: '@' + m.group(1).strip(), s)
    s = RE_URL_EXT.sub(lambda m: f'{m.group(2)} ({m.group(1)})', s)
    s = RE_URL_INT.sub(lambda m: m.group(1), s)
    s = RE_COLOR.sub(lambda m: m.group(1), s)
    s = RE_FONT.sub(lambda m: m.group(1), s)
    s = RE_SIZE.sub(lambda m: m.group(1), s)
    s = RE_IMG.sub(lambda m: m.group(1), s)
    s = RE_LIST.sub(_clean_list_block, s)
    # Простые теги без параметров
    s = RE_SIMPLE.sub('', s)
    s = RE_QUOTE.sub('', s)
    s = RE_CODE.sub('', s)
    # Запасной проход для любых оставшихся парных тегов
    for _ in range(3):
        new = RE_ANY_PAIR.sub(lambda m: m.group(2), s)
        if new == s:
            break
        s = new
    # Удалим одиночные непарные теги
    s = RE_LONE.sub('', s)
    # Чистим пустоты
    s = RE_MULTI_NL.sub('\n\n', s).strip()
    return s


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--limit', type=int, default=0,
                   help='Обработать только первые N сообщений с BBCode (для теста)')
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    with app.app_context():
        # Фильтруем только сообщения с подозрительными тегами
        q = ChatMessage.query.filter(
            db.or_(
                ChatMessage.text.ilike('%[USER=%'),
                ChatMessage.text.ilike('%[URL=%'),
                ChatMessage.text.ilike('%[COLOR=%'),
                ChatMessage.text.ilike('%[B]%'),
                ChatMessage.text.ilike('%[I]%'),
                ChatMessage.text.ilike('%[QUOTE]%'),
                ChatMessage.text.ilike('%[CODE]%'),
                ChatMessage.text.ilike('%[LIST]%'),
                ChatMessage.text.ilike('%[IMG]%'),
                ChatMessage.text.ilike('%[FONT=%'),
                ChatMessage.text.ilike('%[SIZE=%'),
                ChatMessage.text.ilike('%[/'),  # закрывающие теги
            )
        ).order_by(ChatMessage.id.asc())
        total = q.count()
        print(f'mode={"APPLY" if args.apply else "DRY-RUN"}', flush=True)
        print(f'сообщений с BBCode: {total}', flush=True)

        if args.limit:
            msgs = q.limit(args.limit).all()
        else:
            msgs = q.all()

        n_changed = 0
        n_same = 0
        samples = 0
        for m in msgs:
            new = clean(m.text or '')
            if new == m.text:
                n_same += 1
                continue
            n_changed += 1
            if samples < 3:
                print(f'\n#{m.id} BEFORE:\n{m.text[:400]!r}', flush=True)
                print(f'#{m.id} AFTER:\n{new[:400]!r}', flush=True)
                samples += 1
            if args.apply:
                m.text = new
                if n_changed % 500 == 0:
                    db.session.commit()
        if args.apply:
            db.session.commit()
        print(f'\n=== TOTALS ===', flush=True)
        print(f'  обработано: {len(msgs)}', flush=True)
        print(f'  изменено:   {n_changed}', flush=True)
        print(f'  без изменений: {n_same}', flush=True)
        if not args.apply:
            print('\nDRY-RUN — ничего не записано.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
