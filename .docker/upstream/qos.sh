#!/bin/sh
set -eu
if ! tc qdisc show dev lo | grep -q clsact; then tc qdisc add dev lo clsact; fi
tc filter del dev lo egress protocol ip pref 47000 2>/dev/null || true
tc filter add dev lo egress protocol ip pref 47000 flower skip_hw ip_proto tcp src_port 37036 action police rate 2mbit burst 256k mtu 65536 conform-exceed drop
tc filter del dev lo egress protocol ip pref 47001 2>/dev/null || true
tc filter add dev lo egress protocol ip pref 47001 flower skip_hw ip_proto tcp dst_port 37036 action police rate 2mbit burst 256k mtu 65536 conform-exceed drop
tc filter del dev lo egress protocol ip pref 47002 2>/dev/null || true
tc filter add dev lo egress protocol ip pref 47002 flower skip_hw ip_proto tcp src_port 37037 action police rate 2mbit burst 256k mtu 65536 conform-exceed drop
tc filter del dev lo egress protocol ip pref 47003 2>/dev/null || true
tc filter add dev lo egress protocol ip pref 47003 flower skip_hw ip_proto tcp dst_port 37037 action police rate 2mbit burst 256k mtu 65536 conform-exceed drop
tc filter del dev lo egress protocol ip pref 47004 2>/dev/null || true
tc filter add dev lo egress protocol ip pref 47004 flower skip_hw ip_proto tcp src_port 37038 action police rate 2mbit burst 256k mtu 65536 conform-exceed drop
tc filter del dev lo egress protocol ip pref 47005 2>/dev/null || true
tc filter add dev lo egress protocol ip pref 47005 flower skip_hw ip_proto tcp dst_port 37038 action police rate 2mbit burst 256k mtu 65536 conform-exceed drop
tc filter del dev lo egress protocol ip pref 47006 2>/dev/null || true
tc filter add dev lo egress protocol ip pref 47006 flower skip_hw ip_proto tcp src_port 37039 action police rate 2mbit burst 256k mtu 65536 conform-exceed drop
tc filter del dev lo egress protocol ip pref 47007 2>/dev/null || true
tc filter add dev lo egress protocol ip pref 47007 flower skip_hw ip_proto tcp dst_port 37039 action police rate 2mbit burst 256k mtu 65536 conform-exceed drop
