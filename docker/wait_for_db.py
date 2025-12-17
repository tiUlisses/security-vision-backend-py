import os
import time
import psycopg2

def build_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("RTLS_DB_HOST", "db")
    port = os.getenv("RTLS_DB_PORT", "5432")
    user = os.getenv("RTLS_DB_USER", "rtls")
    password = os.getenv("RTLS_DB_PASSWORD", "rtls123")
    name = os.getenv("RTLS_DB_NAME", "rtls_db")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"

def main() -> int:
    timeout_s = int(os.getenv("DB_WAIT_TIMEOUT", "60"))
    interval_s = float(os.getenv("DB_WAIT_INTERVAL", "2"))
    url = build_db_url()
    start = time.time()

    while time.time() - start < timeout_s:
        try:
            conn = psycopg2.connect(url)
            conn.close()
            print("[wait_for_db] Postgres is ready")
            return 0
        except Exception as e:
            print(f"[wait_for_db] waiting for Postgres... ({e})")
            time.sleep(interval_s)

    print("[wait_for_db] ERROR: Postgres not ready")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
