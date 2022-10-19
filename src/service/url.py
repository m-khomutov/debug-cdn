import logging
import re
from typing import List, Tuple


class UrlException(BaseException):
    pass


class Url:
    def __init__(self, url):
        pattern: List[str] = [r'(?P<proto>\w{4})://',
                              r'(?P<auth>[\w]+:[\w%<]+@)?',
                              r'(?P<ip>[\d]{1,3}\.[\d]{1,3}\.[\d]{1,3}\.[\d]{1,3})',
                              r'(?P<port>:[\d]{3,6})?',
                              r'(?P<content>.*)']
        m = re.search(''.join(pattern), url)
        if not m:
            pattern[2] = r'(?P<ip>[\w\.]+)'
            m = re.search(''.join(pattern), url)
            if not m or m['proto'] != 'rtsp':
                raise UrlException(f'invalid url {url}')
        port: int = int(m['port'][1:]) if m['port'] else 554
        self.address: Tuple[str, int] = (m['ip'], port)
        self.content: str = m['content']
        self.credentials: Tuple[str, ...] = tuple()
        if m['auth']:
            self.credentials = tuple(m['auth'][:-1].split(':'))
        logging.info(f'credentials: {self.credentials} address: {self.address} content: {self.content}')
