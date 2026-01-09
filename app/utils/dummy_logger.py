# TODO: É fundamental pensar na lógica de um logger real junto ao Agente e AgnOS.
import logging
import os
import sys

# Códigos ANSI para cores
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

APP_ENV = os.getenv("APP_ENV", "").lower()


def _is_development() -> bool:
    return APP_ENV == "development"


def _get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

    return logger


_logger = _get_logger("app_logger")


def log(message=None, obj=None):
    if not _is_development():
        return

    content = obj if obj is not None else message
    _logger.info(
        f"{BLUE}================== LOG ==================\n{content}{RESET}"
    )


def warning(message=None, obj=None):
    if not _is_development():
        return

    content = obj if obj is not None else message
    _logger.warning(
        f"{YELLOW}================== WARNING ==================\n{content}{RESET}"
    )


def error(message=None, obj=None):
    if not _is_development():
        return

    content = obj if obj is not None else message
    _logger.error(
        f"{RED}================== ERROR ==================\n{content}{RESET}"
    )