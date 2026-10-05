"""
Secure configuration loader
Loads credentials from the project's .env file (see .env.example)
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=PROJECT_ROOT / '.env')


class SecureConfig:
    """Credentials and connection settings from environment variables"""

    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 5432))
    DB_NAME = os.getenv('DB_NAME')
    DB_USER = os.getenv('DB_USER')
    DB_PASSWORD = os.getenv('DB_PASSWORD')

    @classmethod
    def get_database_url(cls, db_type='postgresql'):
        """
        SQLAlchemy URL for the configured database

        Args:
            db_type: 'postgresql' or 'sqlite' (file at data/trading_data.db)
        """
        if db_type == 'sqlite':
            return f"sqlite:///{PROJECT_ROOT / 'data' / 'trading_data.db'}"

        missing = [name for name, value in (('DB_NAME', cls.DB_NAME), ('DB_USER', cls.DB_USER))
                   if not value]
        if missing:
            raise ValueError(
                f"Missing database settings: {', '.join(missing)}. "
                f"Create .env from .env.example in {PROJECT_ROOT} (or set DB_TYPE=sqlite)"
            )

        # URL.create escapes special characters in the password (@, :, / ...)
        # psycopg2 is the installed driver (SQLAlchemy 2.1 defaults to psycopg 3)
        drivername = 'postgresql+psycopg2' if db_type == 'postgresql' else db_type
        return URL.create(
            drivername=drivername,
            username=cls.DB_USER,
            password=cls.DB_PASSWORD,
            host=cls.DB_HOST,
            port=cls.DB_PORT,
            database=cls.DB_NAME,
        )
