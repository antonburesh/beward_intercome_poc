"""Remove the caller's own voice from the audio played in the browser.

The panel sends that voice back: its microphone hears the speaker. The
browser should play the person at the door, not this return.
"""


def _energy(samples):
    return sum(sample * sample for sample in samples)


def _dot(left, right):
    return sum(left[index] * right[index] for index in range(len(left)))


class EchoCanceller:
    def __init__(self):
        self.sent = []
        self.limit = 3200  # 400 ms at 8 kHz

    def reset(self):
        self.sent = []

    def remember(self, samples):
        self.sent.extend(int(sample) for sample in samples)
        if len(self.sent) > self.limit:
            del self.sent[:len(self.sent) - self.limit]

    def clean(self, samples):
        heard = [int(sample) for sample in samples]
        count = len(heard)
        if count == 0 or len(self.sent) < count:
            return heard
        power = _energy(heard)
        if power < 500 * count:
            return heard
        lag, gain, score = self._match(heard, power)
        if score < 0.45:
            return heard
        reference = self.sent[lag:lag + count]
        cleaned = []
        for index in range(count):
            value = int(heard[index] - gain * reference[index])
            if value > 32767:
                value = 32767
            elif value < -32768:
                value = -32768
            cleaned.append(value)
        if _energy(cleaned) < power * 0.25:
            return [0] * count
        return cleaned

    def _match(self, heard, power):
        count = len(heard)
        span = len(self.sent) - count
        step = 8
        best = (0, 0.0, 0.0)
        for lag in range(0, span + 1, step):
            score, gain = self._score(heard, lag, power)
            if score > best[2]:
                best = (lag, gain, score)
        if best[2] == 0:
            return best
        start = max(0, best[0] - step)
        stop = min(span, best[0] + step)
        for lag in range(start, stop + 1):
            score, gain = self._score(heard, lag, power)
            if score > best[2]:
                best = (lag, gain, score)
        return best

    def _score(self, heard, lag, power):
        count = len(heard)
        reference = self.sent[lag:lag + count]
        ref_power = _energy(reference)
        if ref_power < 500 * count:
            return 0.0, 0.0
        corr = _dot(reference, heard)
        gain = corr / ref_power
        score = abs(corr) / (ref_power ** 0.5 * power ** 0.5)
        return score, gain
