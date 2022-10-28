import logging
import time
from . import abs


class Calculator:
    def __init__(self, period: int):
        self._calc_period: int = period
        self._start_time: float = time.time()

    def on_data(self, data: bytes):
        self._on_data(data)
        timing: float = time.time()
        if timing - self._start_time > self._calc_period:
            self._calculate(timing - self._start_time)
            self._start_time = timing

    def _on_data(self, data: bytes):
        raise NotImplemented

    def _calculate(self, period: float):
        raise NotImplemented


class BitrateCalculator (Calculator):
    def __init__(self, period: int):
        super().__init__(period)
        self._bits: int = 0
        self._max: float = .0
        self._min: float = .0
        self._average: float = .0

    def _on_data(self, data: bytes):
        self._bits += len(data) * 8

    def _calculate(self, period: int):
        rate = self._bits / period
        if rate > self._max or not self._max:
            self._max = rate
        if rate < self._min or not self._min:
            self._min = rate
        self._average = (self._average + rate) / 2 if self._average else rate
        logging.info(f'Bitrate={{peak: {rate:.01f},'
                     f' av: {self._average:.01f},'
                     f' max: {self._max:.01f},'
                     f' min: {self._min:.01f}}} b/s.'
                     f' period={period:.04}s.')
        self._bits = 0


class FpsCalculator(Calculator):
    def __init__(self, period: int):
        super().__init__(period)
        self._frames_per_period: int = 0
        self._keyframes_per_period: int = 0

    def _on_data(self, data: bytes):
        self._frames_per_period += 1
        if data[0] & 0x1f == abs.UnitType.IDR:
            self._keyframes_per_period += 1

    def _calculate(self, period: float):
        logging.info(f'FPS={self._frames_per_period / period:.06}'
                     f' frames={self._frames_per_period}'
                     f' period={period:.04}s.'
                     f' keys={self._keyframes_per_period}')
        self._frames_per_period = 0
        self._keyframes_per_period = 0
