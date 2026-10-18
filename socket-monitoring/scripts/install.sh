#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
user_name="$(id -un)"
sudoers_tmp="$(mktemp)"
trap 'rm -f "$sudoers_tmp"' EXIT
printf '%s ALL=(root) NOPASSWD: /usr/bin/ss -H -ltnup\n' "$user_name" > "$sudoers_tmp"
sudo visudo -cf "$sudoers_tmp"
sudoers_dest=/etc/sudoers.d/kali-socket-inventory
if sudo test -e "$sudoers_dest"; then
  if sudo cmp -s "$sudoers_tmp" "$sudoers_dest"; then
    echo 'The exact scoped sudoers rule is already installed.'
  else
    backup="$HOME/.local/share/kali-socket-inventory/backups/kali-socket-inventory.sudoers.$(date +%Y%m%d%H%M%S).bak"
    mkdir -p "$(dirname "$backup")"
    sudo cp -a "$sudoers_dest" "$backup"
    sudo chown "$(id -u):$(id -g)" "$backup"
    sudo chmod 0600 "$backup"
    sudo install -o root -g root -m 0440 "$sudoers_tmp" "$sudoers_dest"
  fi
else
  sudo install -o root -g root -m 0440 "$sudoers_tmp" "$sudoers_dest"
fi
"$repo_dir/socket-monitoring/scripts/deploy-user.sh"
echo 'Exact sudo rule installed for ss -H -ltnup. No Grafana/Prometheus process runs as root.'
