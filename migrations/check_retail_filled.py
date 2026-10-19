"""
Диагностика: насколько заполнены survey_values у сделок Розницы, стоящих
на стадиях с required_dict_codes.

Печатает:
  - всего сделок на required-стадиях
  - у скольких из них ВСЕ 4 обязательных поля заполнены
  - у скольких 3/2/1/0
  - разбивка по стадиям
  - разбивка по кодам (у скольких заполнено конкретно heat / city /
    activity / business_type)

Readonly. Запуск:
    python -u -m migrations.check_retail_filled
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


def main() -> int:
    with app.app_context():
        # 1. Стадии Розницы (id=2) с непустыми required_dict_codes.
        stages = db.session.execute(text("""
            SELECT id, name, required_dict_codes
              FROM deal_stage
             WHERE pipeline_id = 2
               AND jsonb_array_length(required_dict_codes) > 0
             ORDER BY "order"
        """)).fetchall()
        if not stages:
            print('На воронке Розница нет стадий с required_dict_codes.',
                  flush=True)
            return 0

        req_stage_ids = [s.id for s in stages]
        all_codes: set[str] = set()
        for s in stages:
            for c in (s.required_dict_codes or []):
                all_codes.add(c)
        all_codes_sorted = sorted(all_codes)

        print(f'=== Розница (pipeline_id=2) ===', flush=True)
        print(f'  стадий с required_dict_codes: {len(stages)}', flush=True)
        print(f'  все required-коды: {all_codes_sorted}', flush=True)
        print('', flush=True)

        # 2. Общая статистика по сделкам на этих стадиях.
        rows = db.session.execute(text("""
            SELECT COUNT(*) AS total
              FROM deal
             WHERE pipeline_id = 2
               AND stage_id = ANY(:ids)
        """), {'ids': req_stage_ids}).fetchone()
        total = rows.total
        print(f'сделок на required-стадиях: {total}', flush=True)
        print('', flush=True)

        # 3. Распределение по «сколько из 4 заполнено».
        print('=== распределение «сколько из 4 полей заполнено» ===',
              flush=True)
        buckets = {4: 0, 3: 0, 2: 0, 1: 0, 0: 0}
        for row in db.session.execute(text("""
            SELECT survey_values
              FROM deal
             WHERE pipeline_id = 2
               AND stage_id = ANY(:ids)
        """), {'ids': req_stage_ids}):
            sv = row.survey_values or {}
            n = sum(1 for c in all_codes_sorted if sv.get(c))
            buckets[n] = buckets.get(n, 0) + 1
        for k in sorted(buckets.keys(), reverse=True):
            v = buckets[k]
            pct = (v * 100 / total) if total else 0
            print(f'  {k}/4 заполнено: {v:>6}  ({pct:5.1f}%)', flush=True)
        print('', flush=True)

        # 4. Разбивка по кодам: у скольких заполнено конкретно heat/city/…
        print('=== по каждому обязательному коду ===', flush=True)
        for c in all_codes_sorted:
            n = db.session.execute(text(f"""
                SELECT COUNT(*) AS n
                  FROM deal
                 WHERE pipeline_id = 2
                   AND stage_id = ANY(:ids)
                   AND survey_values ? :code
                   AND survey_values ->> :code IS NOT NULL
                   AND survey_values ->> :code <> ''
            """), {'ids': req_stage_ids, 'code': c}).fetchone().n
            pct = (n * 100 / total) if total else 0
            print(f'  {c:<16} {n:>6}  ({pct:5.1f}%)', flush=True)
        print('', flush=True)

        # 5. По стадиям — чтобы увидеть «где у Антона самый пустой хвост».
        print('=== по стадиям (всего / у скольких все 4 заполнены) ===',
              flush=True)
        for s in stages:
            tot = db.session.execute(text("""
                SELECT COUNT(*) AS n
                  FROM deal
                 WHERE pipeline_id = 2 AND stage_id = :sid
            """), {'sid': s.id}).fetchone().n
            # Полностью заполненные — используем свои required-коды,
            # а не общий союз (на разных стадиях может отличаться).
            s_codes = sorted(s.required_dict_codes or [])
            # Все требуются непустыми: ровно для этого стадии.
            if s_codes:
                cond = ' AND '.join([
                    f"(survey_values ? :c{i} AND "
                    f"NULLIF(survey_values ->> :c{i}, '') IS NOT NULL)"
                    for i, _ in enumerate(s_codes)
                ])
                params = {'sid': s.id,
                          **{f'c{i}': c for i, c in enumerate(s_codes)}}
                full = db.session.execute(text(f"""
                    SELECT COUNT(*) AS n
                      FROM deal
                     WHERE pipeline_id = 2
                       AND stage_id = :sid
                       AND {cond}
                """), params).fetchone().n
            else:
                full = tot
            pct = (full * 100 / tot) if tot else 0
            print(f'  id={s.id:<4} {s.name!r:<42} '
                  f'всего={tot:>6}  заполнено={full:>6} ({pct:5.1f}%)',
                  flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
