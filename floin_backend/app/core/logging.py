import logging

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(level: str | None = None) -> None:
    if level is None:
        from app.core.config import get_settings
        level = get_settings().log_level
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format=_FORMAT, force=True)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"floin.{name}")
