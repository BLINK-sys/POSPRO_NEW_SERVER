"""Листинг DealSource с id/name/color/variants/deals для глаза."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from extensions import db
from sqlalchemy import text


def main():
    with app.app_context():
        rows = db.session.execute(text("""
            SELECT
                s.id,
                s.name,
                s.color,
                s.is_active,
                (SELECT COUNT(*) FROM deal d WHERE d.source_id = s.id) AS deals_cnt,
                (SELECT COUNT(*) FROM deal_source_variant v WHERE v.parent_source_id = s.id) AS vars_cnt
            FROM deal_source s
            ORDER BY s.sort_order, s.name
        """)).mappings().fetchall()
        print(f'{"id":>5}  {"color":<8}  {"act":<3}  {"deals":>6}  {"vars":>5}  name', flush=True)
        for r in rows:
            print(f'{r["id"]:>5}  {str(r["color"] or ""):<8}  {"Y" if r["is_active"] else "N":<3}  '
                  f'{r["deals_cnt"]:>6}  {r["vars_cnt"]:>5}  {r["name"]}', flush=True)


if __name__ == '__main__':
    main()
