FROM ghcr.io/kamailio/kamailio-ci:6.1-alpine

COPY kamailio.cfg /etc/kamailio/kamailio.cfg
COPY entrypoint.sh /etc/kamailio/entrypoint.sh
COPY dbtext/version /etc/kamailio/dbtext/version

ENTRYPOINT ["/bin/sh", "/etc/kamailio/entrypoint.sh"]
