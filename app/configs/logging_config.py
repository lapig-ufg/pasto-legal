import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"

_ERROR_FORMATTER = logging.Formatter(
    fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# App-level loggers (replaces agno.utils.log)
app_logger = logging.getLogger("pasto-legal")
service_logger = logging.getLogger("pasto-legal.services")
bridge_logger = logging.getLogger("pasto-legal.bridge")

_APP_LOGGERS: tuple[logging.Logger, ...] = (
    app_logger,
    service_logger,
    bridge_logger,
)


def _build_error_file_handler() -> Optional[RotatingFileHandler]:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            filename=LOG_DIR / "errors.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError as exc:
        print(
            f"[logging_config] WARNING: cannot write error log to {LOG_DIR}/errors.log "
            f"({exc}); error file logging disabled.",
            file=sys.stderr,
        )
        return None
    handler.setLevel(logging.ERROR)
    handler.setFormatter(_ERROR_FORMATTER)
    return handler


def setup_logging(config: Any) -> None:
    """Configure app loggers for Pasto Legal.

    - Errors -> logs/errors.log (rotating 5MB x 3).
    - Info -> terminal in every environment.
    - Debug -> terminal only when config.DEBUG_MODE is True.
    """
    debug_mode = bool(getattr(config, "DEBUG_MODE", False))
    console_level = logging.DEBUG if debug_mode else logging.INFO

    error_handler = _build_error_file_handler()
    error_path = getattr(error_handler, "baseFilename", None)

    for logger in _APP_LOGGERS:
        logger.setLevel(logging.DEBUG)

        if error_handler is not None and not any(
            getattr(h, "baseFilename", None) == error_path
            for h in logger.handlers
        ):
            logger.addHandler(error_handler)

        # Ensure a console handler exists
        has_console = any(
            not isinstance(h, RotatingFileHandler) for h in logger.handlers
        )
        if not has_console:
            console = logging.StreamHandler(sys.stderr)
            console.setLevel(console_level)
            console.setFormatter(
                logging.Formatter("%(levelname)s | %(name)s | %(message)s")
            )
            logger.addHandler(console)
        else:
            for handler in logger.handlers:
                if not isinstance(handler, RotatingFileHandler):
                    handler.setLevel(console_level)
