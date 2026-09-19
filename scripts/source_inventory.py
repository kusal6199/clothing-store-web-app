"""Read-only inventory of the current Prisma PostgreSQL schema."""
import argparse
from pathlib import Path
from urllib.parse import unquote, urlparse
import psycopg


def read_env(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def connect(source_env):
    values = read_env(source_env)
    url = urlparse(values.get("DIRECT_URL") or values["DATABASE_URL"])
    return psycopg.connect(
        host=url.hostname, port=url.port or 5432, dbname=url.path.lstrip("/"),
        user=unquote(url.username), password=unquote(url.password), sslmode="require",
        options="-c default_transaction_read_only=on", connect_timeout=10,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source_env")
    args = parser.parse_args()
    with connect(args.source_env) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")
            for (table,) in cursor.fetchall():
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,))
                columns = [row[0] for row in cursor.fetchall()]
                cursor.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"')
                count = cursor.fetchone()[0]
                print(f"{table}: {count} rows: {', '.join(columns)}")
