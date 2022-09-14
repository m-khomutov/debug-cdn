import logging
import re
import selectors
from enum import IntEnum
from typing import Dict, List, Set, Tuple, Union
from . import abs
from . import rtsp

TagType: IntEnum = IntEnum('TagType', ('AUDIO', 'VIDEO'), start=8)
FrameType: IntEnum = IntEnum('FrameType', ('KEY', 'INTER', 'DISPOSABLE', 'GENERATED', 'INFO'), start=1)
AvcPacketType: IntEnum = IntEnum('AvcPacketType', ('SEQUENCE_HEADER', 'NALU'), start=0)


class FlvHeader:
    def __init__(self, a: bool = False):
        self._data = bytearray(b'\x46\x4c\x56\x01\x01\x00\x00\x00\x09')
        self._data[4] |= (a << 2)

    def __bytes__(self):
        return bytes(self._data)


class FlvTag:
    def __init__(self, tag_type: TagType, length: int, timestamp: int):
        self._data = b''.join([tag_type.to_bytes(1, 'big'),
                               length.to_bytes(3, 'big'),
                               (timestamp & 0xffffff).to_bytes(3, 'big'),
                               (timestamp >> 24).to_bytes(1, 'big'),
                               b'\x00\x00\x00'])

    def __len__(self):
        return len(self._data)

    def __bytes__(self):
        return self._data


class VideoTag(FlvTag):
    def __init__(self, frame_type: FrameType, length: int, timestamp: int):
        super().__init__(TagType.VIDEO, length, timestamp)
        self._data = b''.join([self._data,
                               ((frame_type << 4) | 7).to_bytes(1, 'big')])


class AvcSequenceHeader(VideoTag):
    def __init__(self, data: bytes):
        super().__init__(FrameType.KEY, len(data) + 5, 0)
        self._data = b''.join([self._data,
                               AvcPacketType.SEQUENCE_HEADER.to_bytes(1, 'big'),
                               b'\x00\x00\x00',
                               data])


class AvcNalUnit(VideoTag):
    def __init__(self, frame_type: FrameType, data: bytes, timestamp: int):
        super().__init__(frame_type, len(data) + 5, timestamp)
        self._data = b''.join([self._data,
                               AvcPacketType.NALU.to_bytes(1, 'big'),
                               b'\x00\x00\x00',
                               data])


class FlvBody:
    def __init__(self, tag: FlvTag):
        self._data: bytes = b''.join([bytes(tag), len(tag).to_bytes(4, 'big')])

    def __bytes__(self) -> bytes:
        return self._data


class Connection(abs.Connection):
    def __init__(self):
        self._key: Union[selectors.SelectorKey, None] = None
        self._rtsp_source: Union[abs.Connection, None] = None
        self._avc_header: Union[AvcSequenceHeader, None] = None
        self._timestamp: Union[int, None] = None
        self._sent_key = False

    def disconnect(self, need_to_remove: Set[abs.Connection]) -> None:
        if self._rtsp_source is not None:
            self._rtsp_source.remove_sink(self._key.data.addr)
            if not self._rtsp_source.has_sinks():
                need_to_remove.add(self._rtsp_source)
                self._rtsp_source = None

    def on_read_event(self, **kwargs) -> None:
        key: selectors.SelectorKey = kwargs.get('key')
        data: bytes = key.fileobj.recv(1024)
        if data:
            logging.debug(f'{data.decode("utf-8")}')
            if self._key is None:
                self._key = key
                try:
                    self._set_source(data.decode().split('\r\n'), key.data.addr, **kwargs)
                except BaseException as e:
                    key.data.outb = f'HTTP/1.0 400 Bad Request\r\nWarning: {e}\r\n\r\n'.encode()
            return
        raise EOFError()

    def _set_source(self, headers: List[str], reg_key: Tuple[str, int], **kwargs) -> None:
        connections: Dict[Tuple[str, int], abs.Connection] = kwargs.get('connections')
        if 'GET ' in headers[0]:
            credentials, address, content = self.__class__._parse_url(headers[0].split(' ')[1].lstrip('/'))
            logging.info(f'credentials: {credentials} address: {address} content: {content}')
            if connections.get(address) is None:
                self._rtsp_source = rtsp.Connection(address, rtsp.Source(credentials, content))
                connections[address] = self._rtsp_source
                self._rtsp_source.connect(kwargs.get('selector'))
            else:
                self._rtsp_source = connections.get(address)
            self._rtsp_source.add_sink(self, reg_key)

    def _compile_header(self, sps: bytes, pps: bytes) -> bytes:
        avc_header: AvcSequenceHeader = AvcSequenceHeader(b''.join([b'\x01', sps[1:4],
                                                                    b'\xff\xe1', len(sps).to_bytes(2, 'big'), sps,
                                                                    b'\x01', len(pps).to_bytes(2, 'big'), pps]))
        return b''.join(["HTTP/1.0 200 OK\r\nContent-Type: video/x-flv\r\n\r\n".encode(),
                         bytes(FlvHeader()),
                         b'\x00\x00\x00\x00',
                         bytes(FlvBody(avc_header))])

    @staticmethod
    def _parse_url(url):
        pattern: str = r'(?P<proto>\w{4})://' \
                       r'(?P<auth>[\w]+:[\w%<]+@)?' \
                       r'(?P<ip>[\d]{1,3}\.[\d]{1,3}\.[\d]{1,3}\.[\d]{1,3})' \
                       r'(?P<port>:[\d]{3,6})?' \
                       r'(?P<content>.*)'
        m = re.search(pattern, url)
        if not m or m['proto'] != 'rtsp':
            raise abs.ConnectionException(f'invalid url {url}')
        port: int = int(m['port'][1:]) if m['port'] else 554
        credentials: Tuple[str, ...] = tuple()
        if m['auth']:
            credentials = tuple(m['auth'][:-1].split(':'))
        return credentials, (m['ip'], port), m['content']

    def on_frame(self, frame: bytes, timestamp: int, sps: bytes, pps: bytes) -> None:
        if frame[0] & 0x1F == abs.UnitType.IDR:
            self._on_idr_frame(frame, timestamp, sps, pps)
        elif frame[0] & 0x1f == abs.UnitType.NonIDR and self._sent_key:
            self._on_nonidr_frame(frame, timestamp)

    def _on_idr_frame(self, frame: bytes, timestamp: int, sps: bytes, pps: bytes) -> None:
        rc = b''
        if not self._sent_key:
            rc = self._compile_header(sps, pps)
        if self._timestamp is None:
            self._timestamp = timestamp
        self._key.data.outb = b''.join([rc, bytes(FlvBody(AvcNalUnit(FrameType.KEY,
                                                                    b''.join([len(sps).to_bytes(4, 'big'), sps,
                                                                              len(pps).to_bytes(4, 'big'), pps,
                                                                              len(frame).to_bytes(4, 'big'), frame]),
                                                                    (timestamp - self._timestamp) // 90)))])
        self._sent_key = True

    def _on_nonidr_frame(self, frame: bytes, timestamp: int) -> None:
        self._key.data.outb = bytes(FlvBody(AvcNalUnit(FrameType.INTER,
                                                       b''.join([len(frame).to_bytes(4, 'big'), frame]),
                                                       (timestamp - self._timestamp) // 90
                                                       )
                                            )
                                    )
