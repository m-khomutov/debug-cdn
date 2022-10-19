from collections import namedtuple
from typing import Dict, List, Tuple, Union


Origin: namedtuple = namedtuple('Origin', 'username session_id version network_type address_type address')
Media: namedtuple = namedtuple('Media', 'media port transport formats')


class DescriptionException(BaseException):
    pass


class SessionDescription:
    def __init__(self):
        self._protocol_version: str = ''
        self._origin: Union[Origin, None] = None
        self._session: Tuple[str, str] = ('', '')
        self._uri: str = ''
        self._email: str = ''
        self._phone_number: str = ''
        self._connection_info: str = ''
        self._bandwidth_info: str = ''
        self._active_time: str = ''
        self._repeat_times: List[str] = []
        self._timezone: str = ''
        self._encryption_key: str = ''
        self._attributes: Dict[str, str] = {}

    def parse(self, description: List[str]) -> int:
        lines_parsed: int = 0
        try:
            for line in description:
                d: List[str] = line.split('=')
                {
                    'v': self._set_proto_version,
                    'o': self._set_origin,
                    's': self._set_session_name,
                    'i': self._set_session_info,
                    'u': self._set_uri_of_description,
                    'e': self._set_email_address,
                    'p': self._set_phone_number,
                    'c': self._set_connection_info,
                    'b': self._set_bandwidth_info,
                    't': self._set_session_active_time,
                    'r': self._set_repeat_times,
                    'z': self._set_timezone_adjustments,
                    'k': self._set_encryption_key,
                    'a': self._set_attribute_line,
                    'm': self._on_media,
                }.get(d[0], lambda x: None)('='.join(d[1:]))
                lines_parsed += 1
        except DescriptionException:
            pass
        return lines_parsed

    def attribute(self, key):
        return self._attributes.get(key, None)

    def __repr__(self):
        rc: List[str] = [f'v={self._protocol_version}\r\n'
                         f'o={self._origin.username} '
                         f'{self._origin.session_id} '
                         f'{self._origin.version} '
                         f'{self._origin.network_type} '
                         f'{self._origin.address_type} '
                         f'{self._origin.address}\r\n'
                         f's={self._session[0]}\r\n']
        if self._session[1]:
            rc.append(f'i={self._session[1]}\r\n')
        if self._uri:
            rc.append(f'u={self._uri}\r\n')
        if self._email:
            rc.append(f'e={self._email}\r\n')
        if self._phone_number:
            rc.append(f'p={self._phone_number}\r\n')
        if self._connection_info:
            rc.append(f'c={self._connection_info}\r\n')
        if self._bandwidth_info:
            rc.append(f'b={self._bandwidth_info}\r\n')
        if self._active_time:
            rc.append(f't={self._active_time}\r\n')
        if self._repeat_times:
            rc.extend([f'r={x}\r\n' for x in self._repeat_times])
        if self._timezone:
            rc.append(f'z={self._timezone}\r\n')
        if self._encryption_key:
            rc.append(f'k={self._encryption_key}\r\n')
        if self._attributes:
            rc.extend([f'a={k}:{v}\r\n' for k, v in self._attributes.items()])
        return ''.join(rc)

    def _set_proto_version(self, value: str):
        self._protocol_version = value

    def _set_origin(self, value: str):
        self._origin = Origin(*value.split())

    def _set_session_name(self, value: str):
        self._session = (value, self._session[1])

    def _set_session_info(self, value: str):
        self._session = (self._session[0], value)

    def _set_uri_of_description(self, value: str):
        self._uri = value

    def _set_email_address(self, value: str):
        self._email = value

    def _set_phone_number(self, value: str):
        self._phone_number = value

    def _set_connection_info(self, value: str):
        self._connection_info = value

    def _set_bandwidth_info(self, value: str):
        self._bandwidth_info = value

    def _set_session_active_time(self, value: str):
        self._active_time = value

    def _set_repeat_times(self, value: str):
        self._repeat_times.append(value)

    def _set_timezone_adjustments(self, value: str):
        self._timezone = value

    def _set_encryption_key(self, value: str):
        self._encryption_key = value

    def _set_attribute_line(self, value: str):
        l: List[str, str] = value.split(':')
        self._attributes[l[0]] = l[1]

    def _on_media(self, value: str):
        raise DescriptionException


class MediaDescription:
    def __init__(self):
        self._media: Union[Media, None] = None
        self._title: str = ''
        self._connection_info: str = ''
        self._bandwidth_info: str = ''
        self._encryption_key: str = ''
        self._attributes: Dict[str, str] = {}

    def parse(self, description: List[str]):
        lines_parsed: int = 0
        try:
            for line in description:
                d: List[str] = line.split('=')
                {
                    'm': self._set_media,
                    'i': self._set_title,
                    'c': self._set_connection_info,
                    'b': self._set_bandwidth_info,
                    'k': self._set_encryption_key,
                    'a': self._set_attribute_line,
                }.get(d[0], lambda x: None)('='.join(d[1:]))
                lines_parsed += 1
        except DescriptionException:
            pass
        return lines_parsed

    def media(self) -> str:
        return self._media.media

    def attribute(self, key):
        return self._attributes.get(key, None)

    def __repr__(self):
        rc: List[str] = [f'm={self._media.media} '
                         f'{self._media.port} '
                         f'{self._media.transport} '
                         f'{self._media.formats}\r\n']
        if self._title:
            rc.append(f'i={self._title}\r\n')
        if self._connection_info:
            rc.append(f'c={self._connection_info}\r\n')
        if self._bandwidth_info:
            rc.append(f'b={self._bandwidth_info}\r\n')
        if self._encryption_key:
            rc.append(f'k={self._encryption_key}\r\n')
        if self._attributes:
            rc.extend([f'a={k}:{v}\r\n' for k, v in self._attributes.items()])
        return ''.join(rc)

    def _set_media(self, value: str):
        if self._media:
            raise DescriptionException
        self._media = Media(*value.split())

    def _set_title(self, value: str):
        self._title = value

    def _set_connection_info(self, value: str):
        self._connection_info = value

    def _set_bandwidth_info(self, value: str):
        self._bandwidth_info = value

    def _set_encryption_key(self, value: str):
        self._encryption_key = value

    def _set_attribute_line(self, value: str):
        l: List[str, str] = value.split(':')
        self._attributes[l[0]] = l[1]


class Sdp:
    def __init__(self):
        self._session_description: SessionDescription = SessionDescription()
        self._media_descriptions: Dict[str, MediaDescription] = {}

    def parse(self, description: str):
        d: List[str] = description.splitlines()
        parsed: int = self._session_description.parse(d)
        while parsed < len(d):
            m: MediaDescription = MediaDescription()
            parsed += m.parse(d[parsed:])
            self._media_descriptions[m.media()] = m

    def media(self, key: str):
        return self._media_descriptions.get(key, None)

    def __repr__(self):
        rc: List[str] = [str(self._session_description)]
        rc.extend([str(x) for x in self._media_descriptions.values()])
        return ''.join(rc)
