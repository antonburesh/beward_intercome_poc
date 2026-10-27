#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"

ip=158.160.176.80
mkdir -p config
[ -f config/env ] || cp config.example/env config/env
[ -f config/settings.json ] || cp config.example/settings.json config/settings.json
[ -f config/subscriber ] || cp config.example/subscriber config/subscriber

sed -i "s/^ADVERTISE_IP=.*/ADVERTISE_IP=${ip}/" config/env
sed -i "0,/\"ip\":/s/\"ip\": \"[^\"]*\"/\"ip\": \"${ip}\"/" config/settings.json
awk -F: -v ip="$ip" '
  BEGIN { OFS = ":" }
  NR == 1 { print; next }
  /^[0-9]+:/ { $3 = ip; print; next }
  { print }
' config/subscriber > config/subscriber.tmp
mv config/subscriber.tmp config/subscriber

docker compose -f compose.prod.yaml up -d --build
