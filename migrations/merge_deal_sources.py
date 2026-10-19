"""
Слияние двух DealSource: все сделки и варианты (DealSourceVariant),
ссылающиеся на `src`, переставляются на `dst`, затем `src` удаляется.

Варианты сливаются по имени: если у dst уже есть вариант с таким же name,
сделки src-варианта переставляются на dst-вариант, а сам src-вариант
удаляется. Иначе src-вариант просто меняет parent_source_id на dst.

Dry-run по умолчанию.

Запуск:
    python -u -m migrations.merge_deal_sources --src-name "Партнёр" --dst-name "Партнер"
    python -u -m migrations.merge_deal_sources --src-id 42 --dst-id 7 --apply
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--src-id', type=int)
    p.add_argument('--dst-id', type=int)
    p.add_argument('--src-name', type=str)
    p.add_argument('--dst-name', type=str)
    p.add_argument('--apply', action='store_true',
                   help='Применить (без флага — dry-run)')
    return p.parse_args()


def _resolve(id_, name) -> dict | None:
    if id_:
        return db.session.execute(text(
            "SELECT id, name, color FROM deal_source WHERE id = :i"
        ), {'i': id_}).mappings().fetchone()
    if name:
        # Точное совпадение по name (unique). Сначала case-sensitive, затем
        # case-insensitive — чтобы «Партнёр» нашёлся как `Партнёр`, не `ПАРТНЁР`.
        r = db.session.execute(text(
            "SELECT id, name, color FROM deal_source WHERE name = :n"
        ), {'n': name}).mappings().fetchone()
        if r:
            return r
        return db.session.execute(text(
            "SELECT id, name, color FROM deal_source "
            "WHERE lower(name) = lower(:n)"
        ), {'n': name}).mappings().fetchone()
    return None


def main() -> int:
    args = _parse_args()

    with app.app_context():
        src = _resolve(args.src_id, args.src_name)
        dst = _resolve(args.dst_id, args.dst_name)
        if not src:
            print(f'SRC не найден (id={args.src_id}, name={args.src_name!r})',
                  flush=True)
            return 1
        if not dst:
            print(f'DST не найден (id={args.dst_id}, name={args.dst_name!r})',
                  flush=True)
            return 1
        if src['id'] == dst['id']:
            print('src == dst, нечего делать', flush=True)
            return 0

        print('=== Merge deal_source ===', flush=True)
        print(f'  SRC: id={src["id"]} name={src["name"]!r} color={src["color"]!r}',
              flush=True)
        print(f'  DST: id={dst["id"]} name={dst["name"]!r} color={dst["color"]!r}',
              flush=True)
        print(f'  MODE: {"APPLY" if args.apply else "DRY-RUN"}', flush=True)
        print('', flush=True)

        # 1) Варианты src: пройти по каждому и либо «склеить» (если имя
        # совпадает с существующим dst-вариантом → все сделки на dst-вар,
        # src-вар удалить), либо просто переставить parent на dst.
        src_variants = db.session.execute(text(
            "SELECT id, name FROM deal_source_variant "
            "WHERE parent_source_id = :sid ORDER BY id"
        ), {'sid': src['id']}).mappings().fetchall()
        dst_variants_by_name = {
            r['name']: r['id']
            for r in db.session.execute(text(
                "SELECT id, name FROM deal_source_variant "
                "WHERE parent_source_id = :did"
            ), {'did': dst['id']}).mappings().fetchall()
        }

        n_var_merge = n_var_reparent = n_deals_rebind = 0
        for v in src_variants:
            twin = dst_variants_by_name.get(v['name'])
            if twin:
                # Склейка: все сделки src-варианта → на twin, затем delete.
                cnt = db.session.execute(text(
                    "SELECT COUNT(*) FROM deal WHERE source_variant_id = :vid"
                ), {'vid': v['id']}).scalar() or 0
                print(f'  VAR MERGE #{v["id"]} ({v["name"]!r}) → #{twin}: '
                      f'сделок {cnt}', flush=True)
                n_var_merge += 1
                n_deals_rebind += cnt
                if args.apply:
                    db.session.execute(text(
                        "UPDATE deal SET source_variant_id = :twin "
                        "WHERE source_variant_id = :vid"
                    ), {'twin': twin, 'vid': v['id']})
                    db.session.execute(text(
                        "DELETE FROM deal_source_variant WHERE id = :vid"
                    ), {'vid': v['id']})
            else:
                # Просто перенос родителя.
                print(f'  VAR REPARENT #{v["id"]} ({v["name"]!r}): parent → #{dst["id"]}',
                      flush=True)
                n_var_reparent += 1
                if args.apply:
                    db.session.execute(text(
                        "UPDATE deal_source_variant SET parent_source_id = :did "
                        "WHERE id = :vid"
                    ), {'did': dst['id'], 'vid': v['id']})

        # 2) Остальные сделки src (у которых source_variant_id не было или
        # уже был перенесён) — просто переставить source_id.
        cnt_deals = db.session.execute(text(
            "SELECT COUNT(*) FROM deal WHERE source_id = :sid"
        ), {'sid': src['id']}).scalar() or 0
        print('', flush=True)
        print(f'  DEAL SOURCE_ID: {cnt_deals} сделок {src["id"]} → {dst["id"]}',
              flush=True)
        if args.apply:
            db.session.execute(text(
                "UPDATE deal SET source_id = :did WHERE source_id = :sid"
            ), {'did': dst['id'], 'sid': src['id']})

        # 3) Удаление самого src DealSource. CASCADE подчистит оставшиеся
        # варианты (должно быть 0 после п.1), SET NULL — crm_ingest_source.
        print(f'  DELETE deal_source #{src["id"]}', flush=True)
        if args.apply:
            db.session.execute(text(
                "DELETE FROM deal_source WHERE id = :sid"
            ), {'sid': src['id']})

        if args.apply:
            db.session.commit()
            print('', flush=True)
            print('COMMITTED.', flush=True)
            print(f'  var_merged={n_var_merge}  var_reparented={n_var_reparent}  '
                  f'deals_rebound_via_variant={n_deals_rebind}  '
                  f'deals_direct={cnt_deals}', flush=True)
        else:
            print('', flush=True)
            print('DRY-RUN — ничего не записано. --apply для реального.',
                  flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
