"""The browser must not play the caller's voice that the panel sends back."""

import math
import unittest

from phone.codecs import alaw_to_linear, linear_to_alaw
from phone.echo import EchoCanceller


def tone(frequency, count, amplitude, phase=0):
    return [
        int(amplitude * math.sin(2 * math.pi * frequency * (phase + index) / 8000))
        for index in range(count)
    ]


def energy(samples):
    return sum(sample * sample for sample in samples)


def correlation(left, right):
    count = min(len(left), len(right))
    left = left[:count]
    right = right[:count]
    mean_left = sum(left) / count
    mean_right = sum(right) / count
    var_left = sum((item - mean_left) ** 2 for item in left)
    var_right = sum((item - mean_right) ** 2 for item in right)
    if var_left == 0 or var_right == 0:
        return 0
    mixed = sum((left[i] - mean_left) * (right[i] - mean_right) for i in range(count))
    return mixed / (var_left ** 0.5 * var_right ** 0.5)


class EchoTest(unittest.TestCase):
    def setUp(self):
        self.echo = EchoCanceller()
        self.sent = tone(440, 4000, 8000)
        for index in range(0, len(self.sent), 160):
            self.echo.remember(self.sent[index:index + 160])

    def test_delayed_copy_is_removed(self):
        delay = 800
        echoed = []
        for index in range(len(self.sent)):
            source = self.sent[index - delay] if index >= delay else 0
            echoed.append(int(source * 0.7))
        frame = echoed[2000:2160]
        cleaned = self.echo.clean(frame)
        self.assertLess(energy(cleaned), energy(frame) * 0.1)

    def test_panel_voice_is_kept(self):
        door = tone(300, 160, 9000)
        cleaned = self.echo.clean(door)
        self.assertGreater(correlation(cleaned, door), 0.9)
        self.assertGreater(energy(cleaned), energy(door) * 0.5)

    def test_g711_echo_is_removed_and_door_voice_stays(self):
        delay = 640
        mixed = []
        door = tone(250, 160, 10000)
        for index, sample in enumerate(door):
            source = self.sent[2000 + index - delay]
            coded = alaw_to_linear(linear_to_alaw(int(source * 0.8)))
            mixed.append(max(-32768, min(32767, sample + coded)))
        cleaned = self.echo.clean(mixed)
        self.assertGreater(correlation(cleaned, door), 0.7)
        echo_only = [alaw_to_linear(linear_to_alaw(int(self.sent[2000 + index - delay] * 0.8))) for index in range(160)]
        self.assertLess(abs(correlation(cleaned, echo_only)), 0.5)


if __name__ == "__main__":
    unittest.main()
