#!/usr/bin/env bash
# Read-only, sanitized baseline inventory. Does not print environment variables or log contents.
set -u
printf '%s\n' '== Host =='
cat /etc/os-release | sed -n -E '/^(PRETTY_NAME|VERSION_ID)=/p'
uname -a
hostnamectl --static 2>/dev/null || hostname
uptime
printf '%s\n' '== CPU, memory, pressure =='
lscpu | sed -n -E '/^(Model name|CPU\(s\)|Thread\(s\) per core|Core\(s\) per socket|Socket\(s\)):/p'
free -h
for f in /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io; do test ! -r "$f" || { printf '%s: ' "$f"; cat "$f"; }; done
printf '%s\n' '== Storage =='
lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS
findmnt -rn -o TARGET,SOURCE,FSTYPE,OPTIONS
df -hT
df -ih
printf '%s\n' '== Network =='
ip -brief address
ip route
printf '%s\n' '== Listening ports =='
ss -lntup
printf '%s\n' '== Failed system services =='
systemctl --failed --type=service --no-legend --plain
printf '%s\n' '== Docker containers (no environment/inspect output) =='
if command -v docker >/dev/null 2>&1; then docker ps -a --format 'table {{.Names}}\t{{.State}}\t{{.Status}}\t{{.Image}}'; fi
printf '%s\n' '== User services =='
systemctl --user list-units --type=service --state=running --no-legend
printf '%s\n' '== VMware running VM count =='
if command -v vmrun >/dev/null 2>&1; then vmrun list | sed -n '1p' | awk '{print $1}'; else echo 'vmrun unavailable'; fi
printf '%s\n' '== Error journal count since boot (contents omitted) =='
journalctl -p err -b --no-pager -o cat 2>/dev/null | wc -l
