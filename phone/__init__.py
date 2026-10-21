"""Local SIP softphone.

app.py       start with: python3 phone/app.py
settings.json  SIP account 101 and the door panels on this LAN
config.py    loads settings.json
page.py      browser page
sip.py       registration, calls, RTP
sdp.py       SDP offer and answer
codecs.py    G.711 and RTP payload parsing
h264.py      H.264 depacketizer for the live picture
door.py      snapshot and door open for one panel
httpapi.py   HTTP routes on 127.0.0.1:8090
"""
