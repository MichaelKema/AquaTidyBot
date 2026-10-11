#!/bin/bash
set -euo pipefail
test -d /var/lib/aquatidy/data
image=$(cat /var/lib/aquatidy/image)
export DOCKER_CONFIG=/var/lib/aquatidy/docker
# A replacement instance restores its saved image from the persistent disk.
docker image inspect "$image" > /dev/null 2>&1 || docker pull "$image"
exec /usr/bin/docker run --rm --name aquatidy \
  --env-file /var/lib/aquatidy/bot.env \
  --env DATABASE_PATH=/data/aquatidy.sqlite3 \
  --volume /var/lib/aquatidy/data:/data \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  "$image"
