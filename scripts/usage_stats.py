#!/usr/bin/env python3
"""Usage stats from fact_dingtalk_bot_call_log (MySQL).

  python scripts/usage_stats.py
  python scripts/usage_stats.py --days 30
  python scripts/usage_stats.py --days 7 --by day
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.env import load_env_files, monorepo_env_paths  # noqa: E402

def _connect():
    try:
        import pymysql
    except ModuleNotFoundError as exc:
        raise SystemExit("need pymysql: pip install pymysql") from exc
    host = (os.getenv("DB_HOST") or "").strip()
    user = (os.getenv("DB_USER") or "").strip()
    database = (os.getenv("DB_NAME") or "").strip()
    if not host or not user or not database:
        raise SystemExit("missing DB_HOST/DB_USER/DB_NAME (load .env)")
    return pymysql.connect(
        host=host,
        port=int(os.getenv("DB_PORT") or "3306"),
        user=user,
        password=os.getenv("DB_PASSWORD") or "",
        database=database,
        charset="utf8mb4",
        connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT_SEC") or "5"),
        cursorclass=pymysql.cursors.DictCursor,
    )


def _table() -> str:
    name = (os.getenv("BOT_CALL_LOG_TABLE") or "fact_dingtalk_bot_call_log").strip()
    if not name.replace("_", "").isalnum():
        raise SystemExit(f"bad table name: {name!r}")
    return name


def _feature_sql(alias: str = "event_type") -> str:
    # 合并 CP 双记：logistics ROUTE_CP + cp RECEIVED → 同一功能
    return f"""
    CASE
      WHEN {alias} IN ('ROUTE_CP', 'RECEIVED') THEN '1 发货单核对'
      WHEN {alias} = 'ROUTE_SPLIT' THEN '2 标签/PDF拆分'
      WHEN {alias} = 'ROUTE_PINXIANG' THEN '3 不分仓拼箱'
      WHEN {alias} = 'ROUTE_LCL' THEN '4 分仓拼箱'
      ELSE CONCAT(COALESCE(bot_module,''), ':', {alias})
    END
    """


def _print_table(rows: list[dict], cols: list[str]) -> None:
    if not rows:
        print("(empty)")
        return
    widths = {c: max(len(c), max(len(str(r.get(c) or "")) for r in rows)) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c) or "").ljust(widths[c]) for c in cols))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="dingtalk-bots usage stats")
    parser.add_argument("--days", type=int, default=30, help="lookback days (default 30)")
    parser.add_argument(
        "--by",
        choices=("feature", "user", "user-feature", "day"),
        default="feature",
        help="aggregation (default feature)",
    )
    args = parser.parse_args(argv)

    load_env_files(monorepo_env_paths(ROOT))
    table = _table()
    feat = _feature_sql("event_type")
    where = "created_at >= NOW() - INTERVAL %s DAY"
    # 一次使用 = logistics 的 ROUTE_*（cp.RECEIVED 与 ROUTE_CP 成对，不重复计）
    # %% for pymysql literal %
    scope = "bot_module = 'logistics' AND event_type LIKE 'ROUTE\\_%%'"

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS n FROM `{table}` WHERE {where} AND {scope}",
                (args.days,),
            )
            total = cur.fetchone()["n"]
            print(f"period: last {args.days} days | events: {total} | table: {table}\n")

            if args.by == "feature":
                cur.execute(
                    f"""
                    SELECT {feat} AS feature, COUNT(*) AS times, COUNT(DISTINCT user_id) AS users
                    FROM `{table}`
                    WHERE {where} AND {scope}
                    GROUP BY feature
                    ORDER BY times DESC
                    """,
                    (args.days,),
                )
                _print_table(list(cur.fetchall()), ["feature", "times", "users"])
            elif args.by == "user":
                cur.execute(
                    f"""
                    SELECT COALESCE(NULLIF(user_name,''), user_id) AS user,
                           user_id,
                           COUNT(*) AS times
                    FROM `{table}`
                    WHERE {where} AND {scope}
                    GROUP BY user_id, user_name
                    ORDER BY times DESC
                    """,
                    (args.days,),
                )
                _print_table(list(cur.fetchall()), ["user", "user_id", "times"])
            elif args.by == "user-feature":
                cur.execute(
                    f"""
                    SELECT COALESCE(NULLIF(user_name,''), user_id) AS user,
                           {feat} AS feature,
                           COUNT(*) AS times
                    FROM `{table}`
                    WHERE {where} AND {scope}
                    GROUP BY user_id, user_name, feature
                    ORDER BY user, times DESC
                    """,
                    (args.days,),
                )
                _print_table(list(cur.fetchall()), ["user", "feature", "times"])
            else:  # day
                cur.execute(
                    f"""
                    SELECT DATE(created_at) AS day,
                           {feat} AS feature,
                           COUNT(*) AS times
                    FROM `{table}`
                    WHERE {where} AND {scope}
                    GROUP BY day, feature
                    ORDER BY day DESC, times DESC
                    """,
                    (args.days,),
                )
                _print_table(list(cur.fetchall()), ["day", "feature", "times"])
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
