"""Run the existing loader using backend/.env, keeping the DSN out of CLI history."""
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from load_case import main

if __name__ == '__main__':
    load_dotenv(Path(__file__).resolve().parents[1] / 'backend/.env', override=False)
    dsn = os.getenv('SUPABASE_DATABASE_URL')
    if not dsn:
        raise SystemExit('Set SUPABASE_DATABASE_URL in backend/.env first.')
    if '--dsn' in sys.argv[1:]:
        raise SystemExit('Use SUPABASE_DATABASE_URL in backend/.env rather than --dsn.')
    raise SystemExit(main(['--dsn', dsn, *sys.argv[1:]]))
