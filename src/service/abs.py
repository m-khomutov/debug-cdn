from __future__ import annotations
from enum import IntEnum
import selectors
from abc import ABC
from typing import Set, Tuple


class UnitType(IntEnum):
    NonIDR = 1,
    IDR = 5,
    FU_A = 28


class ConnectionException(BaseException):
    pass


class Connection(ABC):
    def connect(self, selector: selectors.DefaultSelector) -> None:
        raise NotImplemented()

    def disconnect(self, need_to_remove: Set[Connection]) -> None:
        pass

    def on_read_event(self, **kwargs) -> None:
        raise NotImplemented()

    @staticmethod
    def on_write_event(key: selectors.SelectorKey) -> None:
        if key.data.outb:
            sent = key.fileobj.send(key.data.outb)  # Should be ready to write
            key.data.outb = key.data.outb[sent:]

    def on_sdp(self, sdp):
        raise NotImplemented()

    def on_video(self, frame: bytes, timestamp: int, sps: bytes, pps: bytes) -> None:
        raise NotImplemented()

    def on_audio(self, frame: bytes, timestamp: int) -> None:
        raise NotImplemented()

    def add_sink(self, connection: Connection, reg_key: Tuple[str, int]) -> None:
        raise NotImplemented()

    def remove_sink(self, reg_key: Tuple[str, int]) -> None:
        raise NotImplemented()

    def has_sinks(self) -> bool:
        raise NotImplemented()
