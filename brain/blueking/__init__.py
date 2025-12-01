import logging
import sys

from . import blueking_pb2 as _blueking_pb2

_ = sys.modules.setdefault("blueking_pb2", _blueking_pb2)

from . import blueking_pb2_grpc as _blueking_pb2_grpc

_ = sys.modules.setdefault("blueking_pb2_grpc", _blueking_pb2_grpc)

blueking_pb2 = _blueking_pb2
blueking_pb2_grpc = _blueking_pb2_grpc


def configure_logging(log_file: str = "latest.log", log_level: int = logging.INFO) -> None:
    """
    Ensure a file handler is attached to the root logger for persistent logs.

    :param log_file: Path to the log file that should capture Brain output.
    :param log_level: Minimum log level to record.
    :return: None.
    """
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and handler.get_name() == "blueking_latest_log":
            return

    file_handler = logging.FileHandler(
        log_file,
        mode="w",
        encoding="utf-8",
    )
    file_handler.set_name("blueking_latest_log")
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    if root_logger.level > log_level or root_logger.level == logging.NOTSET:
        root_logger.setLevel(log_level)


configure_logging()
