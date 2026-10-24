#!/bin/sh
# Start Kamailio and the phone on this host, then check that 101 is registered.
# Usage: sh deploy/up.sh 158.160.176.80
set -eu

ip=${1:?address}
cd "$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"

mkdir -p config
if [ ! -f config/env ]; then
  cp config.example/env config/env
fi
if [ ! -f config/settings.json ]; then
  cp config.example/settings.json config/settings.json
fi
if [ ! -f config/subscriber ]; then
  cp config.example/subscriber config/subscriber
fi

sed -i "s/^ADVERTISE_IP=.*/ADVERTISE_IP=${ip}/" config/env
# The first ip is the SIP server. Panel addresses are left alone.
sed -i "0,/\"ip\":/s/\"ip\": \"[^\"]*\"/\"ip\": \"${ip}\"/" config/settings.json
awk -F: -v ip="$ip" '
  NR == 1 { print; next }
  /^[0-9]+:/ { $3 = ip; OFS = ":"; print; next }
  { print }
' config/subscriber > config/subscriber.tmp
mv config/subscriber.tmp config/subscriber

if ! command -v docker >/dev/null 2>&1; then
  echo "На сервере нет docker" >&2
  exit 1
fi
if docker info >/dev/null 2>&1; then
  dc="docker"
else
  dc="sudo docker"
fi

$dc compose -f compose.prod.yaml up -d --build --wait --wait-timeout 180

ok=0
i=0
while [ "$i" -lt 30 ]; do
  if curl -sf http://127.0.0.1:8090/api/state | grep -q '"registered": true'; then
    ok=1
    break
  fi
  i=$((i + 1))
  sleep 2
done

if [ "$ok" != 1 ]; then
  $dc compose -f compose.prod.yaml logs --tail 80 || true
  echo "Телефон не зарегистрировался на Kamailio" >&2
  exit 1
fi

curl -sf http://127.0.0.1:8090/api/state
echo
dump=$($dc compose -f compose.prod.yaml exec -T kamailio kamcmd -s unix:/tmp/kamailio_ctl ul.dump)
printf '%s\n' "$dump"
printf '%s\n' "$dump" | grep -q 'sip:101@' || {
  echo "Kamailio не видит контакт телефона 101" >&2
  exit 1
}
