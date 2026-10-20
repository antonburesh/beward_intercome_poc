"""Parse an SDP offer and build the softphone answer."""

def parse_offer(body):
    session_ip = None
    sections = []
    current = None
    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith("c=IN IP4 ") and current is None:
            session_ip = line.split()[-1]
        elif line.startswith("m="):
            parts = line.split()
            current = {
                "kind": parts[0][2:],
                "port": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0,
                "proto": parts[2] if len(parts) > 2 else "RTP/AVP",
                "payloads": [int(p) for p in parts[3:] if p.isdigit()],
                "ip": session_ip,
                "rtpmap": {},
                "fmtp": {},
            }
            sections.append(current)
        elif current is not None and line.startswith("c=IN IP4 "):
            current["ip"] = line.split()[-1]
        elif current is not None and line.startswith("a=rtpmap:"):
            pt, _, enc = line[9:].partition(" ")
            if pt.isdigit():
                current["rtpmap"][int(pt)] = enc
        elif current is not None and line.startswith("a=fmtp:"):
            pt, _, params = line[7:].partition(" ")
            if pt.isdigit():
                current["fmtp"][int(pt)] = params
    for section in sections:
        if section["kind"] != "video":
            continue
        for pt, enc in section["rtpmap"].items():
            if enc.upper().startswith("H264"):
                section["h264"] = pt
                section["fmtp_h264"] = section["fmtp"].get(pt, "packetization-mode=1;profile-level-id=42e01f")
                break
    return sections, session_ip


def sdp_media(body):
    sections, _ = parse_offer(body)
    for section in sections:
        if section["kind"] == "audio" and section["port"]:
            return section["ip"], section["port"]
    return None, None


def answer_sdp(user, local_ip, audio_port, video_port, offer):
    """SDP answer for one offer: PCMA audio and H.264 when the offer has it."""
    sections, _ = parse_offer(offer or "")
    lines = [
        "v=0",
        f"o={user} 0 0 IN IP4 {local_ip}",
        "s=door-poc",
        f"c=IN IP4 {local_ip}",
        "t=0 0",
    ]
    answered_video = False
    for section in sections:
        if section["kind"] == "audio":
            lines += [
                f"m=audio {audio_port} RTP/AVP 8",
                "a=rtpmap:8 PCMA/8000",
                "a=sendrecv",
            ]
        elif section["kind"] == "video" and section.get("h264") and not answered_video:
            pt = section["h264"]
            fmtp = section.get("fmtp_h264") or "packetization-mode=1;profile-level-id=42e01f"
            lines += [
                f"m=video {video_port} RTP/AVP {pt}",
                f"a=rtpmap:{pt} H264/90000",
                f"a=fmtp:{pt} {fmtp}",
                "a=sendrecv",
            ]
            answered_video = True
        else:
            lines.append(f"m={section['kind']} 0 {section['proto']} 0")
    if not any(section["kind"] == "audio" for section in sections):
        lines += [
            f"m=audio {audio_port} RTP/AVP 8",
            "a=rtpmap:8 PCMA/8000",
            "a=sendrecv",
        ]
    return ("\r\n".join(lines) + "\r\n").encode()
