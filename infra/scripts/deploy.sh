#!/bin/bash
# Called as root over authenticated SSH. Never enable shell tracing here.
set -euo pipefail
umask 077

for _ in $(seq 1 120); do
  [ -f /run/aquatidy-ready ] && break
  sleep 5
done
[ -f /run/aquatidy-ready ] || { echo 'Host bootstrap is not ready' >&2; exit 1; }
mountpoint -q /var/lib/aquatidy
exec 9>/run/aquatidy-deploy.lock
flock -w 300 9

image=${1:?Supply an immutable GHCR image digest}
repository=$(jq -r .repository /etc/aquatidy.json)
if [[ ! "$image" =~ ^ghcr\.io/[^@]+@sha256:[a-f0-9]{64}$ ]] || \
   [[ "$image" != "ghcr.io/$repository@sha256:"* ]]; then
  echo 'Image must be an immutable digest from the configured repository' >&2
  exit 1
fi
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# Secret payload arrives on stdin, never in process arguments or Terraform state.
cat > "$work/secret.json"
export DOCKER_CONFIG=/var/lib/aquatidy/docker
reminder_timezone=$(jq -r .REMINDER_TIMEZONE "$work/secret.json")
[[ "$reminder_timezone" =~ ^[A-Za-z0-9_+/-]+$ ]]
jq -e '.Discord_Token | type == "string"' "$work/secret.json" > /dev/null
jq -e '.Discord_Token | length > 0 and test("^[^\\r\\n]+$")' "$work/secret.json" > /dev/null
{
  jq -r '"Discord_Token=" + .Discord_Token' "$work/secret.json"
  printf 'REMINDER_TIMEZONE=%s\n' "$reminder_timezone"
} > "$work/bot.env"

# Public packages need no login. Private packages need a read:packages token.
if jq -e '.GHCR_TOKEN | type == "string" and length > 0' "$work/secret.json" > /dev/null; then
  username=$(jq -er '.GHCR_USERNAME | select(type == "string" and length > 0)' "$work/secret.json")
  jq -r .GHCR_TOKEN "$work/secret.json" | docker login ghcr.io --username "$username" --password-stdin > /dev/null
else
  docker logout ghcr.io > /dev/null 2>&1 || true
fi
docker pull "$image"

previous=''
[ ! -f /var/lib/aquatidy/image ] || previous=$(cat /var/lib/aquatidy/image)
[ ! -f /var/lib/aquatidy/bot.env ] || cp /var/lib/aquatidy/bot.env "$work/previous.env"
printf '%s\n' "$image" > "$work/image"
rollback() {
  trap - ERR
  set +e
  echo 'Deployment failed; restoring previous configuration' >&2
  systemctl stop aquatidy
  if [ -n "$previous" ] && [ -f "$work/previous.env" ]; then
    printf '%s\n' "$previous" > /var/lib/aquatidy/image
    install -m 600 "$work/previous.env" /var/lib/aquatidy/bot.env
    systemctl reset-failed aquatidy
    systemctl start aquatidy
  else
    rm -f /var/lib/aquatidy/image /var/lib/aquatidy/bot.env
  fi
  exit 1
}
# Pull first, then stop the singleton before replacing configuration.
trap rollback ERR
systemctl stop aquatidy
install -m 600 "$work/bot.env" /var/lib/aquatidy/bot.env
install -m 600 "$work/image" /var/lib/aquatidy/image
systemctl reset-failed aquatidy
systemctl start aquatidy
sleep 20

# Process-level smoke check: a live Discord integration check is still required.
if systemctl is-active --quiet aquatidy && \
   [ "$(systemctl show aquatidy -p NRestarts --value)" = 0 ] && \
   [ "$(docker inspect --format '{{.State.Running}}' aquatidy 2>/dev/null)" = true ]; then
  echo "Deployed $image"
else
  rollback
fi
trap - ERR
