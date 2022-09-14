import argparse
import logging
import selectors
import socket
import time
import types
from typing import Dict, Set, Tuple
from .abs import Connection
from .flv import Connection as Flv


class ServiceException(BaseException):
    pass


class Service:
    def __init__(self):
        self._connections: Dict[Tuple[str, int], Connection] = {}
        self._selector = selectors.DefaultSelector()
        self._accept_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def __del__(self):
        self._accept_sock.close()
        self._selector.close()

    def run(self, bind_port: int):
        """Starts managing RTSP protocol network activity"""
        while True:
            try:
                self._accept_sock.bind(('0.0.0.0', bind_port))
                break
            except OSError as e:
                logging.error(e)
                time.sleep(2)
        self._accept_sock.listen()
        self._accept_sock.setblocking(False)
        self._selector.register(self._accept_sock, selectors.EVENT_READ, data=None)
        logging.info('Ok')
        need_to_remove: Set[Connection] = set()
        while True:
            try:
                for key, mask in self._selector.select(timeout=.01):
                    if key.data is None:
                        sock, address = key.fileobj.accept()
                        sock.setblocking(False)
                        self._selector.register(sock,
                                                selectors.EVENT_READ | selectors.EVENT_WRITE,
                                                types.SimpleNamespace(addr=address, inb=b'', outb=b''))
                        self._connections[address] = Flv()
                        logging.debug(f'new connection from {address}')
                    else:
                        try:
                            self._on_event(key, mask, need_to_remove)
                        except BaseException as e:  # noqa # pylint: disable=bare-except
                            logging.error(f'Exception: {e}')
                            self._selector.unregister(key.fileobj)
                            key.fileobj.close()
                            self._connections[key.data.addr].disconnect(need_to_remove)
                            self._connections.pop(key.data.addr, None)
                            logging.debug(f'connection to {key.data.addr} closed')
            except KeyboardInterrupt:
                break

    def _on_event(self, key, mask, need_to_remove: Set[Connection]) -> None:
        """Manages event read/write on socket"""
        connect = self._connections.get(key.data.addr, None)
        if connect:
            if connect in need_to_remove:
                raise ServiceException('stop reading from rtsp source')
            if mask & selectors.EVENT_READ:
                connect.on_read_event(selector=self._selector, key=key, connections=self._connections)
            elif mask & selectors.EVENT_WRITE:
                connect.on_write_event(key)


def run():
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description='rtsp->flv timestamping test service')
    parser.add_argument('-port', type=int, default=5566, help='http binding port to stream flv(def. 5566)')
    parser.add_argument('-loglevel',
                        type=str,
                        default='info',
                        help='logging level (critical|error|warning|info|debug def. info)')
    args: argparse.Namespace = parser.parse_args()
    level = {
        'critical': lambda: logging.CRITICAL,
        'error': lambda: logging.ERROR,
        'warning': lambda: logging.WARNING,
        'info': lambda: logging.INFO,
        'debug': lambda: logging.DEBUG,
    }.get(args.loglevel, logging.NOTSET)()
    logging.getLogger().setLevel(level)
    Service().run(args.port)