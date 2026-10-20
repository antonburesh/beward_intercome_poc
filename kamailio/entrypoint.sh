#!/bin/sh
set -eu

if [ -z "${ADVERTISE_IP:-}" ]; then
  echo "ADVERTISE_IP is required" >&2
  exit 1
fi

sed "s/__ADVERTISE_IP__/${ADVERTISE_IP}/g" /etc/kamailio/kamailio.cfg > /tmp/kamailio.cfg
exec kamailio -DD -E -m 64 -M 8 -f /tmp/kamailio.cfg
