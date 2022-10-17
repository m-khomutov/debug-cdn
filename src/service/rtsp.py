"""Rtsp client"""
import logging
import selectors
import socket
import time
import types
from base64 import b64encode
from collections import namedtuple
from enum import IntEnum
from hashlib import md5
from typing import Dict, Tuple, Union
from . import abs


State: IntEnum = IntEnum('State', ('INITIAL',
                                   'DESCRIBED',
                                   'SETUP',
                                   'ASK_PLAYING',
                                   'PLAYING')
                         )
SequenceSetType: IntEnum = IntEnum('SequenceSetType', ('SPS', 'PPS'), start=7)


RtpInterleaved: namedtuple = namedtuple('RtpInterleaved', 'preamble channel size')
RtpHeader: namedtuple = namedtuple('RtpHeader', 'version P X CC M pt cseq timestamp ssrc')
UnitHeader: namedtuple = namedtuple('UnitHeader', 'f nri type')
FUHeader: namedtuple = namedtuple('FUHeader', 's e r type')


class RtspException(BaseException):
    pass


class Source:
    def __init__(self, credentials: tuple, content: str, fps: Union[int, None]) -> None:
        self.credentials = credentials
        self.content: str = content
        self._fps: Union[int, None] = fps
        self._start_fps: int = time.time()
        self._frames_per_period: int = 0
        self._keyframes_per_period: int = 0
        self.sink_table: Dict[Tuple[str, int], Connection] = {}
        self._sequence: int = 1
        self._buffer: bytearray = bytearray()
        self._interleaved: RtpInterleaved = RtpInterleaved('$', 0, 0)
        self._state: State = State.INITIAL
        self.url: str = ''
        self._control: list = []
        self._session: str = ''
        self._transport: str = ''
        self.range = []
        self._authorization: list = ['', '']
        self.ha1: str = ''
        self.nonce: str = ''
        self.timestamp_delta: list = [0, 0]
        self._timeout: int = 0
        self._last_keepalive: int = 0
        self._keepalive: str = ''
        self._timing = time.time()
        self._credentials_not_accepted = 0
        self._frame: bytearray = bytearray()
        self.sps: bytes = b''
        self.pps: bytes = b''

    def stream_request(self, address: str, port: int) -> bytes:
        if not self.content:
            self.content = '/'
        self.url = ''.join([f'rtsp://{address}:{port}', f'{self.content}'])
        self._keepalive = f"OPTIONS {self.url} RTSP/1.0\r\n" \
                          f"CSeq: {self._sequence}\r\n" \
                          f"User-Agent: debug-cdn\r\n" \
                          f"{self._get_authorization('OPTIONS')}\r\n"
        logging.debug(self._keepalive)
        return self._keepalive.encode()

    def on_stream(self, key: selectors.SelectorKey, data: bytes) -> None:
        if self._state == State.PLAYING:
            self._on_rtp_data(data)
            if self._timeout and time.time() - self._last_keepalive > self._timeout - 3:
                self._last_keepalive = time.time()
                key.data.outb = self._keepalive.encode()
        else:
            try:
                if self._session:
                    reply_end = data.find(0x24)
                else:
                    reply_end = data.find(b'\x0d\x0a\x0d\x0a')
                if reply_end != 0:
                    key.data.outb = self._on_rtsp_dialog(data[:reply_end].decode('utf-8').split('\r\n'),
                                                         data[reply_end + 4:])
                elif reply_end >= 0 and self._session:
                    self._state = State.PLAYING
                    self._on_rtp_data(data[reply_end:])
            except UnicodeDecodeError:
                self._state = State.PLAYING

    def clear(self):
        self._state: State = State.INITIAL
        self._session = ''
        self.timestamp_delta = [0, 0]
        self._buffer.clear()

    def _on_rtsp_dialog(self, headers: list, remains: bytes) -> bytes:
        logging.debug('\n'.join(headers)+'\n')
        self._set_status(headers[0])
        rc = b''
        if not (self._status == 200 or self._status == 401):
            raise RtspException(f'Source {self.url} not found')
        for hdr in headers:
            out_bytes: bytes = {
                'CSeq': self._set_sequence,
                'Public': self._ask_describe,
                'Content-Base': self._set_content,
                'Content-Length': self._set_content,
                'Session': self._set_session,
                'Transport': self._set_transport,
                'WWW-Authenticate': self._set_authentication
            }.get(hdr.split(':')[0], lambda **h: b'')(header=hdr, body=remains)
            if out_bytes:
                rc = out_bytes
        if self._state == State.SETUP:
            rc = self._ask_play()
        if rc:
            logging.debug(rc.decode('utf-8'))
        return rc

    def _on_rtp_data(self, data: bytes):
        self._buffer += data
        if self._buffer[0] != 0x24:
            reply_end = self._buffer.find(b'\x0d\x0a\x0d\x0a')
            if reply_end >= 0:
                logging.debug(self._buffer[:reply_end+4].decode())
                self._buffer = self._buffer[reply_end + 4:]
            else:
                return
        while True:
            interleaved: RtpInterleaved = RtpInterleaved(str(self._buffer[0]),
                                                         self._buffer[1],
                                                         int.from_bytes(self._buffer[2:4], byteorder='big'))
            if len(self._buffer) > interleaved.size + 8:
                header: RtpHeader = RtpHeader((self._buffer[4] >> 6) & 3,
                                              (self._buffer[4] >> 5) & 1,
                                              (self._buffer[4] >> 4) & 1,
                                              (self._buffer[4]) & 0xf,
                                              (self._buffer[5] >> 7) & 1,
                                              (self._buffer[5]) & 0x7f,
                                              int.from_bytes(self._buffer[6:8], byteorder='big'),
                                              int.from_bytes(self._buffer[8:12], byteorder='big'),
                                              int.from_bytes(self._buffer[12:16], byteorder='big'))
                unit: UnitHeader = UnitHeader(self._buffer[16] >> 7,
                                              (self._buffer[16] >> 5) & 3,
                                              (self._buffer[16]) & 0x1f)
                if unit.type == abs.UnitType.FU_A:
                    fu_header: FUHeader = FUHeader(self._buffer[17] >> 7,
                                                   (self._buffer[17] >> 6) & 1,
                                                   (self._buffer[17] >> 5) & 1,
                                                   (self._buffer[17]) & 0x1f)
                    if fu_header.s:
                        self._frame = ((unit.f << 7) | (unit.nri << 5) | fu_header.type).to_bytes(1, 'big')
                    self._frame += self._buffer[18:interleaved.size + 4]
                    if fu_header.e:
                        self._on_frame_ready(header)
                else:
                    self._frame = self._buffer[16:interleaved.size + 4]
                    self._on_frame_ready(header)
                self._buffer = self._buffer[interleaved.size + 4:]
            else:
                break

    def _on_frame_ready(self, header: RtpHeader):
        if self._frame[0] & 0x1f == SequenceSetType.SPS:
            self.sps = self._frame
        elif self._frame[0] & 0x1f == SequenceSetType.PPS:
            self.pps = self._frame
        if self.sps and self.pps:
            for sink in self.sink_table.values():
                sink.on_frame(self._frame, header.timestamp, self.sps, self.pps)
        self._initialize_timestamp_set(header)
        logging.info(f'{hex(self._frame[0])} '
                     f'{header.timestamp} '
                     f'{header.timestamp - self.timestamp_delta[1]} '
                     f'{int((time.time() - self._timing) * 1000)}')
        self.timestamp_delta[1] = header.timestamp
        self._timing = time.time()
        if self._fps:
            self._frames_per_period += 1
            if self._frame[0] & 0x1f == abs.UnitType.IDR:
                self._keyframes_per_period += 1
            if self._timing - self._start_fps > self._fps:
                logging.info(f'FPS={self._frames_per_period / (self._timing - self._start_fps):.06}'
                             f' frames={self._frames_per_period}'
                             f' period={self._timing - self._start_fps:.04}s.'
                             f' keys={self._keyframes_per_period}')
                self._start_fps = self._timing
                self._frames_per_period = 0
                self._keyframes_per_period = 0

    def _initialize_timestamp_set(self, header: RtpHeader):
        if not self.timestamp_delta[0]:
            self.timestamp_delta = [header.timestamp, header.timestamp]

    def _set_status(self, header: str) -> None:
        self._status = int(header.split()[1])

    def _set_sequence(self, **kwargs) -> None:
        self._sequence = int(kwargs.get('header').split()[1]) + 1

    def _set_content(self, **kwargs) -> bytes:
        if self._state == State.DESCRIBED:
            return b''
        body: bytes = kwargs.get('body')
        logging.debug(body.decode("utf-8"))
        self._state = State.DESCRIBED
        if kwargs.get('header'):
            self._content_base = kwargs.get('header').split()[1]
        description = body.decode('utf-8').split('\r\n')
        self._control = [x.split('a=control:')[1] for x in description if 'a=control:' in x and '*' not in x]
        if len(self._control) > 2:
            self._control = self._control[1:3]
        if not self.range:
            range_hdr = [x.split(':')[1].split('=')[1] for x in description if 'a=range:' in x]
            if range_hdr:
                self.range = range_hdr[0].split('-')
        url: str = self._control[0] if 'rtsp://' in self._control[0] else self._content_base + self._control[0]
        return f'SETUP {url} RTSP/1.0\r\n'\
               f'Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n' \
               f'CSeq: {self._sequence}\r\n' \
               f'User-Agent: debug-cdn\r\n' \
               f'{self._get_authorization("SETUP")}\r\n'.encode()

    def _set_session(self, **kwargs) -> None:
        if not self._session:
            self._state = State.SETUP
            self._session = kwargs.get('header').split()[1].strip()
            if ';' in self._session:
                l: list = self._session.split(';')
                self._session = l[0]
                self._timeout = [int(x.split('=')[1]) for x in l[1:] if 'timeout' in x][0]
                self._last_keepalive = time.time()
        else:
            self._state = State.PLAYING

    def _set_transport(self, **kwargs) -> None:
        self._transport = kwargs.get('header').split()[1]

    def _set_authentication(self, **kwargs) -> bytes:
        if self._credentials_not_accepted > 4:
            raise RtspException(f'Credentials {self.credentials} Not Accepted')
        self._credentials_not_accepted += 1
        realm = kwargs.get('header').split()[1]
        if realm.startswith('Basic'):
            self._set_basic_authentication()
        elif realm.startswith('Digest'):
            self._set_digest_authentication(kwargs.get('header'))
        return self._ask_describe()

    def _set_basic_authentication(self):
        self._authorization[0] = 'Authorization: Basic ' + \
                                 b64encode(f'{self.credentials[0]}:'
                                           f'{self.credentials[1]}'.encode()).decode('ascii') + '\r\n'

    def _set_digest_authentication(self, header):
        params: dict = {}
        for p in header.split('Digest')[1].split(','):
            p = p.strip().split('=')
            params[p[0]] = p[1].strip('"')
        self.ha1 = md5((self.credentials[0] + ':' +
                        params['realm'] + ':' +
                        self.credentials[1]).encode('utf-8')).hexdigest()
        self.nonce = params['nonce']
        self._authorization[1] = f'Authorization: Digest username="{self.credentials[0]}",' \
                                 f' realm="{params["realm"]}",' \
                                 f' nonce="{self.nonce}",' \
                                 f' uri="{self.url}",' \
                                 f' algorithm="MD5",' \
                                 f' response="'

    def _ask_describe(self, **kwargs) -> bytes:
        return f'DESCRIBE {self.url} RTSP/1.0\r\n' \
               f'Accept: application/sdp\r\n' \
               f'CSeq: {self._sequence}\r\n' \
               f'User-Agent: debug-cdn\r\n' \
               f'{self._get_authorization("DESCRIBE")}\r\n'.encode()

    def _ask_play(self) -> bytes:
        self._state = State.ASK_PLAYING
        range_hdr: str = 'npt=now--'
        if self.range:
            range_type: str = 'clock' if 'T' in self.range[0] else 'npt'
            range_hdr = f'{range_type}={self.range[0]}-{self.range[1]}'
        return f'PLAY {self._content_base} RTSP/1.0\r\n' \
               f'CSeq: {self._sequence}\r\n' \
               f'Range: {range_hdr}\r\n' \
               f'User-Agent: debug-cdn\r\n' \
               f'Session: {self._session}\r\n' \
               f'{self._get_authorization("PLAY")}\r\n'.encode()

    def _get_authorization(self, method):
        if self._authorization[1]:
            ha2 = md5((method + ':' + self.url).encode('utf-8')).hexdigest()
            response: str = md5((self.ha1 + ':' + self.nonce + ':' + ha2).encode('utf-8')).hexdigest()
            return ''.join([self._authorization[1], response, '"\r\n'])
        return self._authorization[0]


class Connection(abs.Connection):
    """Class to connect to stream source"""
    def __init__(self, address, proto) -> None:
        self._address: Tuple[str, int] = address
        self._proto = proto
        self._stream_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def __repr__(self):
        return f'{self.__class__.__name__}(ip {self._address[0]} port {self._address[1]})'

    def connect(self, selector: selectors.DefaultSelector) -> None:
        try:
            self._stream_socket.connect(self._address)
        except socket.error as err:
            raise RtspException(err)
        self._stream_socket.setblocking(False)
        selector.register(self._stream_socket,
                          selectors.EVENT_READ | selectors.EVENT_WRITE,
                          types.SimpleNamespace(addr=self._address,
                                                inb=b'',
                                                outb=self._proto.stream_request(self._address[0], self._address[1])))

    def on_read_event(self, **kwargs):
        key: selectors.SelectorKey = kwargs.get('key')
        data: bytes = key.fileobj.recv(1024)
        if data:
            return self._proto.on_stream(key, data)
        raise EOFError()

    def add_sink(self, connection: abs.Connection, reg_key: Tuple[str, int]) -> None:
        self._proto.sink_table[reg_key] = connection

    def remove_sink(self, reg_key: Tuple[str, int]) -> None:
        self._proto.sink_table.pop(reg_key, None)

    def has_sinks(self) -> bool:
        return len(self._proto.sink_table) != 0
