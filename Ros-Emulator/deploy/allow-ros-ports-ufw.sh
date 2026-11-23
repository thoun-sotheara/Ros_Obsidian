#!/usr/bin/env sh
set -eu

sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 20013/udp
sudo ufw allow 20015/udp
sudo ufw status
