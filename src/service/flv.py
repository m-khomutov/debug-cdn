import logging
import selectors
from base64 import b64decode
from enum import IntEnum
from typing import Dict, List, Set, Tuple, Union
from . import abs
from . import rtsp
from . import sdp
from . url import Url

TagType: IntEnum = IntEnum('TagType', ('AUDIO', 'VIDEO'), start=8)
FrameType: IntEnum = IntEnum('FrameType', ('KEY', 'INTER', 'DISPOSABLE', 'GENERATED', 'INFO'), start=1)
AvcPacketType: IntEnum = IntEnum('AvcPacketType', ('SEQUENCE_HEADER', 'NALU'), start=0)
SoundFormat: IntEnum = IntEnum('SoundFormat', ('LPCM_PE',
                                               'ADPCM',
                                               'MP3',
                                               'LPCM_LE',
                                               'NM16',
                                               'NM8',
                                               'NM',
                                               'A_LAW',
                                               'U_LAW',
                                               'reserved',
                                               'AAC'
                                               ), start=0
                               )
SoundRate: IntEnum = IntEnum('SoundRate', ('fr5.5KHz', 'fr11KHz', 'fr22KHz', 'fr44KHz'), start=0)
SoundSize: IntEnum = IntEnum('SoundSize', ('SND8', 'SND16'), start=0)
SoundType: IntEnum = IntEnum('SoundType', ('MONO', 'STEREO'), start=0)
AacPacketType: IntEnum = IntEnum('AacPacketType', ('SEQUENCE_HEADER', 'RAW'), start=0)


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


class AudioData:
    def __init__(self, f: SoundFormat, r: SoundRate, s: SoundSize, t: SoundType):
        self._fmt: SoundFormat = f
        self._rate: SoundRate = r
        self._size: SoundSize = s
        self._type: SoundType = t

    def __bytes__(self) -> bytes:
        return (((self._fmt & 15) << 4) |
                ((self._rate & 3) << 2) |
                ((self._size & 1) << 1) |
                (self._type & 1)
                ).to_bytes(1, 'big')


class AudioTag(FlvTag):
    def __init__(self, sample: bytes, timestamp: int, data: AudioData, packet_type: AacPacketType):
        super().__init__(TagType.AUDIO, len(sample) + 2, timestamp)
        self._data = b''.join([self._data, bytes(data), packet_type.to_bytes(1, 'big'), sample])


class FlvBody:
    def __init__(self, tag: FlvTag):
        self._data: bytes = b''.join([bytes(tag), len(tag).to_bytes(4, 'big')])

    def __bytes__(self) -> bytes:
        return self._data


class Timestamp:
    def __init__(self, frequency: float):
        self._value: Union[int, None] = None
        self._aux: float = .0
        self._clock_rate: float = frequency / 1000.

    def get(self, timestamp: int) -> int:
        if self._value is None:
            self._value = timestamp
        ts: float = (timestamp - self._value) / self._clock_rate
        rc: int = int(ts)
        self._aux += ts - rc
        if self._aux > 1.:
            self._aux -= 1
            rc += 1
        return rc


class Connection(abs.Connection):
    def __init__(self):
        self._key: Union[selectors.SelectorKey, None] = None
        self._rtsp_source: Union[abs.Connection, None] = None
        self._avc_header: Union[AvcSequenceHeader, None] = None
        self._timestamp: Dict[str, Union[Timestamp, None]] = {'video': None, 'audio': None}
        self._sent_key = False
        self._audio_data = AudioData(SoundFormat.AAC, SoundRate.fr44KHz, SoundSize.SND16, SoundType.STEREO)

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
            url: Url = Url(headers[0].split(' ')[1].lstrip('/'))
            if connections.get(url.address) is None:
                self._rtsp_source = rtsp.Connection(url.address, rtsp.Source(url.credentials, url.content, None))
                self._rtsp_source.add_sink(self, reg_key)
                connections[url.address] = self._rtsp_source
                self._rtsp_source.connect(kwargs.get('selector'))
            else:
                self._rtsp_source = connections.get(url.address)
                self._rtsp_source.add_sink(self, reg_key)

    @staticmethod
    def _compile_avc_header(sps: bytes, pps: bytes) -> bytes:
        return bytes(FlvBody(AvcSequenceHeader(b''.join([b'\x01', sps[1:4],
                                                         b'\xff\xe1', len(sps).to_bytes(2, 'big'), sps,
                                                         b'\x01', len(pps).to_bytes(2, 'big'), pps]))))

    def _compile_aac_header(self, attrib: List[str]) -> bytes:
        frq_idx: Dict[int, int] = {96000: 0,
                                   88200: 1,
                                   64000: 2,
                                   48000: 3,
                                   44100: 4,
                                   32000: 5,
                                   24000: 6,
                                   22050: 7,
                                   16000: 8,
                                   12000: 9,
                                   11025: 10,
                                   8000: 11,
                                   7350: 12
                                   }
        object_type: int = 2
        clock_rate = int(attrib[0])
        channels = int(attrib[1]) if len(attrib) > 1 else 1
        idx: int = frq_idx.get(clock_rate, None) if frq_idx.get(clock_rate) else 15
        self._timestamp['audio'] = Timestamp(clock_rate)
        if idx == 15:
            conf = bytes.fromhex(hex(((object_type & 0x1f) << 35) |
                                     ((idx & 15) << 31) |
                                     ((clock_rate & 0xffffff) << 7) |
                                     ((channels & 15) << 3)
                                     )[2:]
                                 )
        else:
            conf = bytes.fromhex(hex(((object_type & 0x1f) << 11) |
                                     ((idx & 15) << 7) |
                                     ((channels & 15) << 3)
                                     )[2:]
                                 )
        return bytes(FlvBody(AudioTag(conf, 0, self._audio_data, AacPacketType.SEQUENCE_HEADER)))

    def on_sdp(self, sdp_: sdp.Sdp):
        rc: List[bytes] = ["HTTP/1.0 200 OK\r\nContent-Type: video/x-flv\r\n\r\n".encode(),
                           bytes(FlvHeader(sdp_.media('audio') is not None)),
                           b'\x00\x00\x00\x00'
                           ]
        if sdp_.media('video') and sdp_.media('video').attribute('fmtp'):
            sprop = sdp_.media('video').attribute('fmtp').split('sprop-parameter-sets=')[1].split(';')[0]
            sprop = sprop.split(',')
            rc.append(self.__class__._compile_avc_header(b64decode(sprop[0]), b64decode(sprop[1])))
            self._timestamp['video'] = Timestamp(90000.)
        if sdp_.media('audio') and sdp_.media('audio').attribute('rtpmap'):
            attrib: List[str] = sdp_.media('audio').attribute('rtpmap').split()[1].split('/')
            if attrib[0].upper() == 'MPEG4-GENERIC':
                rc.append(self._compile_aac_header(attrib[1:]))
        self._key.data.outb = b''.join(rc)

    def on_video(self, frame: bytes, timestamp: int, sps: bytes, pps: bytes) -> None:
        if frame[0] & 0x1F == abs.UnitType.IDR:
            self._on_idr_frame(frame, self._timestamp['video'].get(timestamp), sps, pps)
        elif frame[0] & 0x1f == abs.UnitType.NonIDR and self._sent_key:
            self._on_nonidr_frame(frame, self._timestamp['video'].get(timestamp))

    def on_audio(self, sample: bytes, timestamp: int) -> None:
        rc: List[bytes] = [bytes(FlvBody(AudioTag(sample,
                                                  self._timestamp['audio'].get(timestamp),
                                                  self._audio_data,
                                                  AacPacketType.RAW)))]
        self._key.data.outb = b''.join(rc)

    def _on_idr_frame(self, frame: bytes, timestamp: int, sps: bytes, pps: bytes) -> None:
        self._key.data.outb = bytes(FlvBody(AvcNalUnit(FrameType.KEY,
                                                       b''.join([len(sps).to_bytes(4, 'big'), sps,
                                                                 len(pps).to_bytes(4, 'big'), pps,
                                                                 len(frame).to_bytes(4, 'big'), frame]
                                                                ),
                                                       timestamp
                                                       )
                                            )
                                    )
        self._sent_key = True

    def _on_nonidr_frame(self, frame: bytes, timestamp: int) -> None:
        self._key.data.outb = bytes(FlvBody(AvcNalUnit(FrameType.INTER,
                                                       b''.join([len(frame).to_bytes(4, 'big'), frame]),
                                                       timestamp
                                                       )
                                            )
                                    )
