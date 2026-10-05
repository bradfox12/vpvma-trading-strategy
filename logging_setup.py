"""
Shared logging configuration for all entry-point scripts

- Log files live in <project>/logs/ regardless of the working directory
- Files are UTF-8 and rotate (5 × 5 MB)
- Console output never crashes on emoji/unicode (Windows cp1252 consoles)
- Uncaught exceptions are written to the log, not only stderr

Usage (call once, from main()):
    from logging_setup import setup_logging
    logger = setup_logging('portfolio_manager')
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / 'logs'
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'


def _make_console_safe(stream):
    """Replace unencodable characters instead of raising UnicodeEncodeError"""
    reconfigure = getattr(stream, 'reconfigure', None)
    if reconfigure is not None:
        try:
            reconfigure(errors='replace')
        except (ValueError, OSError):
            pass


def setup_logging(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Configure the root logger with a rotating UTF-8 file and a safe console handler.

    Args:
        name: Log file stem, e.g. 'daily_update' -> logs/daily_update.log
        level: Minimum level for both handlers

    Returns:
        Logger named `name`
    """
    LOG_DIR.mkdir(exist_ok=True)

    _make_console_safe(sys.stdout)
    _make_console_safe(sys.stderr)

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_DIR / f'{name}.log', maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Third-party libraries are noisy at INFO
    for noisy in ('urllib3', 'sqlalchemy.engine'):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    def _log_uncaught(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logging.getLogger(name).critical('Uncaught exception', exc_info=(exc_type, exc, tb))

    sys.excepthook = _log_uncaught

    return logging.getLogger(name)
