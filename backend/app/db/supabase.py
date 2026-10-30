import psycopg

from app.config import settings


def check_connectivity() -> bool:
	"""Open and close a PostgreSQL connection to verify database access."""
	with psycopg.connect(settings.supabase_database_url) as connection:
		with connection.cursor() as cursor:
			cursor.execute("SELECT 1")

	return True
