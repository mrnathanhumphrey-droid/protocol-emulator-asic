#!/usr/bin/env bash
# on-box setup: unpack the yosys bundle + jobs + toy; yosys's share dir also to /usr/share/yosys; check the pinned banner.
set -uo pipefail
cd /home/ubuntu/eqbox || exit 2
tar xzf ybin.tgz && tar xzf jobs.tgz && tar xzf toy.tgz || { echo "untar failed"; exit 2; }
sudo mkdir -p /usr/share/yosys && sudo cp -r ybin/share/yosys/. /usr/share/yosys/
V="$(ybin/bin/yosys -V)"; echo "yosys: $V"; python3 -V; nproc; free -g | head -2
[ "$V" = "Yosys 0.52 (git sha1 fee39a3284c90249e1d9684cf6944ffbbcbb8f90)" ] && echo SETUP_OK || echo SETUP_BAD
