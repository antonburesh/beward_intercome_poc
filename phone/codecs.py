"""G.711 A-law/μ-law and RTP payload extraction."""

import struct


def alaw_to_linear(value):
    value ^= 0x55
    sign = value & 0x80
    exponent = (value & 0x70) >> 4
    mantissa = value & 0x0F
    sample = mantissa << 4
    if exponent:
        sample = (sample + 0x108) << (exponent - 1)
    else:
        sample += 8
    return sample if sign else -sample


def linear_to_alaw(sample):
    sample >>= 3
    if sample >= 0:
        mask = 0xD5
    else:
        mask = 0x55
        sample = -sample - 1
    segment = 8
    for index, end in enumerate((0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF)):
        if sample <= end:
            segment = index
            break
    if segment >= 8:
        value = 0x7F
    else:
        value = segment << 4
        shift = 1 if segment < 2 else segment
        value |= (sample >> shift) & 0x0F
    return (value ^ mask) & 0xFF


def linear_to_ulaw(sample):
    """G.711 μ-law. Silence 0 encodes to 255, matching audioop.lin2ulaw."""
    if sample > 32635:
        sample = 32635
    elif sample < -32635:
        sample = -32635
    sign = 0
    if sample < 0:
        sign = 0x80
        sample = -sample
    sample += 0x84
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not (sample & mask):
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return (~(sign | (exponent << 4) | mantissa)) & 0xFF


def ulaw_to_linear(value):
    value = (~value) & 0xFF
    sign = value & 0x80
    exponent = (value >> 4) & 0x07
    mantissa = value & 0x0F
    sample = ((mantissa << 3) + 0x84) << exponent
    sample -= 0x84
    return -sample if sign else sample


def rtp_packet(packet):
    if len(packet) < 12 or (packet[0] >> 6) != 2:
        return None
    cc = packet[0] & 0x0F
    extension = (packet[0] >> 4) & 0x01
    marker = (packet[1] >> 7) & 0x01
    payload_type = packet[1] & 0x7F
    offset = 12 + cc * 4
    if extension:
        if len(packet) < offset + 4:
            return None
        length = struct.unpack("!H", packet[offset + 2:offset + 4])[0]
        offset += 4 + length * 4
    if offset > len(packet):
        return None
    payload = packet[offset:]
    if packet[0] & 0x20:
        if not payload or payload[-1] > len(payload):
            return None
        payload = payload[:-payload[-1]]
    return payload_type, marker, payload
