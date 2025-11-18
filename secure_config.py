"""
Secure configuration loader
Loads sensitive credentials from .env file using python-dotenv
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)


class SecureConfig:
    """
    Secure configuration class for sensitive credentials
    All values are loaded from environment variables (.env file)
    """
    
    # Database credentials
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 5432))
    DB_NAME = os.getenv('DB_NAME')
    DB_USER = os.getenv('DB_USER')
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    
    # API credentials
    MARKET_API_KEY = os.getenv('MARKET_API_KEY')
    MARKET_API_SECRET = os.getenv('MARKET_API_SECRET')
    
    # Optional: Additional API keys
    ALPHA_VANTAGE_KEY = os.getenv('ALPHA_VANTAGE_KEY')
    POLYGON_KEY = os.getenv('POLYGON_KEY')
    FINNHUB_KEY = os.getenv('FINNHUB_KEY')
    EOD_API_KEY = os.getenv('EOD_API_KEY')
    
    @classmethod
    def validate(cls):
        """
        Validate that all required credentials are present
        Raises ValueError if any required credential is missing
        """
        required_vars = [
            ('DB_NAME', cls.DB_NAME),
            ('DB_USER', cls.DB_USER),
            ('DB_PASSWORD', cls.DB_PASSWORD),
            ('MARKET_API_KEY', cls.MARKET_API_KEY),
        ]
        
        missing = [var_name for var_name, value in required_vars if not value]
        
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                f"Please check your .env file. See .env.example for template."
            )
    
    @classmethod
    def get_database_url(cls, db_type='postgresql'):
        """
        Generate database connection URL
        
        Args:
            db_type: Database type ('postgresql', 'mysql', 'sqlite')
        
        Returns:
            str: Database connection URL
        """
        if db_type == 'sqlite':
            return f"sqlite:///data/trading_data.db"
        
        return (
            f"{db_type}://{cls.DB_USER}:{cls.DB_PASSWORD}"
            f"@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"
        )


# Validate on import (optional - comment out if you want lazy validation)
# SecureConfig.validate()