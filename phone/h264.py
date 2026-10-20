"""H.264 RTP depacketizer and avcC decoder configuration."""

import base64
import re
import struct


def sprop_nals(fmtp):
    match = re.search(r"sprop-parameter-sets=([^;,\s]+(?:,[^;,\s]+)*)", fmtp or "")
    if not match:
        return []
    nals = []
    for part in match.group(1).split(","):
        try:
            nals.append(base64.b64decode(part))
        except (ValueError, TypeError):
            continue
    return nals


def avc_decoder_config(sps, pps):
    return (
        b"\x01" + sps[1:4] + b"\xff\xe1"
        + struct.pack("!H", len(sps)) + sps
        + b"\x01" + struct.pack("!H", len(pps)) + pps
    )


def depacketize(payload, fu):
    """Turn one H.264 RTP payload into NAL units.

    fu is the in-progress FU-A buffer, or None. Returns (nals, fu).
    """
    nal_type = payload[0] & 0x1F
    nals = []
    if nal_type == 28 and len(payload) >= 2:
        start = payload[1] & 0x80
        end = payload[1] & 0x40
        header = bytes([(payload[0] & 0xE0) | (payload[1] & 0x1F)])
        if start:
            fu = bytearray(header)
            fu += payload[2:]
        elif fu is not None:
            fu += payload[2:]
        if end and fu is not None:
            nals.append(bytes(fu))
            fu = None
    elif nal_type == 24:
        index = 1
        while index + 2 <= len(payload):
            size = struct.unpack("!H", payload[index:index + 2])[0]
            index += 2
            nals.append(payload[index:index + size])
            index += size
    elif 1 <= nal_type <= 23:
        nals.append(payload)
    return nals, fu
