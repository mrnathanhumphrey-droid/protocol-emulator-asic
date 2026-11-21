#!/usr/bin/env bash
# Bundle WSL's yosys 0.52 (apt, sha fee39a3) to run on any x86-64 Linux through its OWN loader + libs.
set -euo pipefail
B=/tmp/yb_$$; rm -rf $B; mkdir -p $B/ybin/bin $B/ybin/lib $B/ybin/share
cp /usr/bin/yosys $B/ybin/bin/yosys.real; cp /usr/bin/yosys-abc $B/ybin/bin/yosys-abc.real
cp /lib64/ld-linux-x86-64.so.2 $B/ybin/bin/ld.so
for f in /usr/bin/yosys /usr/bin/yosys-abc; do ldd $f | awk '/=> \//{print $3}'; done | sort -u | xargs -I{} cp -L {} $B/ybin/lib/
cp -r /usr/share/yosys $B/ybin/share/yosys
for t in yosys yosys-abc; do
  printf '#!/bin/sh\nD=$(dirname "$(readlink -f "$0")")\nexec "$D/ld.so" --library-path "$D/../lib" "$D/%s.real" "$@"\n' $t > $B/ybin/bin/$t
  chmod +x $B/ybin/bin/$t
done
tar -C $B -czf "$1" ybin; rm -rf $B; ls -la "$1"
