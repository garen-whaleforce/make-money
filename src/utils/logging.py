"""Logging utilities"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler


def setup_logging(
    level: str = "INFO",
    log_format: str = "rich",
    log_file: Optional[Path] = None,
) -> None:
    """Setup logging configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_format: Format type ('rich' or 'json')
        log_file: Optional file path for logging
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    handlers = []

    if log_format == "rich":
        console = Console(stderr=True)
        handlers.append(
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_time=True,
                show_path=False,
            )
        )
        format_str = "%(message)s"
    else:
        handlers.append(logging.StreamHandler(sys.stderr))
        format_str = (
            '{"time": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": "%(message)s"}'
        )

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            logging.Formatter(
                '{"time": "%(asctime)s", "level": "%(levelname)s", '
                '"logger": "%(name)s", "message": "%(message)s"}'
            )
        )
        handlers.append(file_handler)

    logging.basicConfig(
        level=log_level,
        format=format_str,
        handlers=handlers,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
