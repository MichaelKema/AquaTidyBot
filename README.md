# AquaTidyBot

A Discord bot with reaction roles and reminders to hydrate, check bottles, and clean rooms.

[Add the bot to your server](https://discord.com/oauth2/authorize?client_id=1247629331660931082&permissions=8796361590784&integration_type=0&scope=bot).

## Setup

Requires Python 3.10+ and a Discord bot token. Enable the **Message Content** and **Server Members** privileged intents in the Discord developer portal. The bot needs View Channel, Send Messages, Read Message History, Add Reactions and Manage Roles permissions; its role must be above the roles it assigns.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set Discord_Token.
python AquaTidy.py
```

An administrator runs `!start [channel] [timezone]` in each server, for example:

```text
!start #bot-channel America/New_York
```

The bot prompts for custom role names (or uses 🥤 Bottle Check, 💧 Hydrated, 🧹 Clean Room), creates missing roles, and posts a reaction message. Configuration is saved per server after the message and reactions are created. Re-running setup replaces that server's association and resets its reminder deadlines. Existing roles on members are retained.

The optional timezone is an IANA name. Its default is `REMINDER_TIMEZONE` from `.env`, or `UTC`. Each server's timezone is saved in SQLite, so changing the environment does not change existing server settings; rerun setup to change them.

## Scheduling and recovery

Hydration reminders run every two hours and bottle reminders every three hours, beginning at setup. Room reminders run on Saturdays at 00:00, 04:00, 08:00, 12:00, 16:00 and 20:00 in the configured timezone, including daylight saving changes. The host timezone does not affect scheduling.

Three loops start in `setup_hook()`, wait for Discord readiness, and check persisted UTC deadlines every minute. Repeated ready events do not start additional loops. A late iteration or restart sends **one catch-up reminder per overdue type and server**, even if Saturday has already ended, then advances to the next future deadline. Missed reminders are coalesced instead of replayed in a burst. Failed sends keep their deadlines and retry on a later check.

Raw reaction events let the saved role message work after a restart without depending on Discord's message cache. Changes made while the bot is offline are not replayed.

Successful sends are recorded after Discord accepts the message. A process crash between sending and saving can result in a duplicate catch-up message. Run one bot instance against this database; it does not coordinate multiple replicas.

## Persistent container deployment

```sh
cp .env.example .env
# Set the token and optionally REMINDER_TIMEZONE in .env.
docker compose up -d --build
```

Compose binds **`./data` on the host to `/data` in the container** and sets `DATABASE_PATH=/data/aquatidy.sqlite3`. Replacing or restarting the container retains the database. Keep this host directory when replacing the application, and copy it to the new host when moving servers. Never commit the token or database.

For a non-container deployment, `DATABASE_PATH` defaults to `data/aquatidy.sqlite3`. Point it at a durable writable directory if the application directory is replaced on deployment. To back up or restore, stop the bot, copy the database, then restart. Configuration from the older in-memory version cannot be recovered after it exits; run `!start` once per server after upgrading.

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests cover server isolation, SQLite reopening, delayed and missed Saturday reminders, persisted delivery, all Saturday slots, DST, periodic cadence, failed sends, loop lifecycle, and reactions to saved messages after restart. They run without a Discord token or network access.

## CI/CD and Terraform (AWS Lightsail)

GitHub Actions tests pull requests, validates Terraform, and builds the Docker image. Successful default-branch builds publish to GHCR and can deploy to Lightsail using GitHub OIDC and temporary SSH access. Terraform supports your existing AquaTidy instance or can provision a new Lightsail instance, with persistent storage and a scoped deployment role.

See [infra/README.md](infra/README.md) for provisioning, existing-instance setup, required GitHub variables/secrets, and recovery. Deployment stays inactive until the repository variables are configured.
