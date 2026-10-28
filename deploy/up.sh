#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
ip=158.160.176.80
dir=/etc/sip-server

if [ "$(id -u)" -eq 0 ]; then
  mkdir -p "$dir"
else
  sudo mkdir -p "$dir"
  sudo chown "$(id -u):$(id -g)" "$dir"
fi

if [ ! -f "$dir/subscriber" ] && [ -f config/subscriber ]; then
  cp -a config/. "$dir/"
fi

[ -f "$dir/env" ] || cp config.example/env "$dir/env"
[ -f "$dir/settings.json" ] || cp config.example/settings.json "$dir/settings.json"
[ -f "$dir/subscriber" ] || cp config.example/subscriber "$dir/subscriber"

sed -i "s/^ADVERTISE_IP=.*/ADVERTISE_IP=${ip}/" "$dir/env"
sed -i "0,/\"ip\":/s/\"ip\": \"[^\"]*\"/\"ip\": \"${ip}\"/" "$dir/settings.json"
awk -F: -v ip="$ip" '
  BEGIN { OFS = ":" }
  NR == 1 { print; next }
  /^[0-9]+:/ { $3 = ip; print; next }
  { print }
' "$dir/subscriber" > "$dir/subscriber.tmp"
mv "$dir/subscriber.tmp" "$dir/subscriber"

# The server's saved ghcr.io login cannot pull the public Kamailio image.
nocreds=$(mktemp -d)
printf '%s\n' '{"auths":{}}' > "$nocreds/config.json"
DOCKER_CONFIG=$nocreds docker compose -f compose.prod.yaml up -d --build
rm -rf "$nocreds"
