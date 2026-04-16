# WhatsApp mirror + scheduler panel

This project mirrors WhatsApp messages from one group to another using [Green API](https://green-api.com/), and includes a web panel to manage scheduled religious messages.

## What it does

- Mirrors new messages from one or more source groups to a destination group (`SOURCE_GROUP_CHAT_ID` plus optional `SOURCE_GROUP_CHAT_IDS`).
- Deduplicates **outgoing text** (after link strip + optional group link) so the same content is not posted twice within `DEDUPE_WINDOW_SECONDS`, whether it came from the source group or from the scheduler/panel.
- Appends your group link to outgoing messages (optional).
- Runs an admin panel with login on Railway.
- Lets you create, enable/disable, delete, and send-now scheduled messages.
- Preserves your rich formatting text exactly as you paste it in the panel.

## Setup

1. Create a Green API instance and connect your WhatsApp.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill values.
4. In Green API console enable:
   - Incoming messages and files
   - Messages sent from phone
5. Run: `python index.py`

## Railway deployment

1. Push repository to GitHub.
2. Create Railway project from this repo.
3. Set Railway Variables from `.env.example`.
4. Deploy.

Railway will run:
- WhatsApp mirror loop
- Scheduled message worker
- Admin panel web server

## Admin panel

- URL: `https://<your-railway-domain>/`
- Login uses `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
- In the panel, add:
  - Title
  - Time (`HH:MM`, 24-hour)
  - Days
  - Full message content (your Arabic formatted text with icons)

## Example pair (source → destination)

Typical setup:

- Source group (mirror from): `SOURCE_GROUP_CHAT_ID=120363404953877602@g.us`
- Destination group (post into): `DESTINATION_GROUP_CHAT_ID=120363406394094973@g.us`

Use your real `@g.us` values from Green API / WhatsApp group info.

## Environment variables

Keep sensitive values in env only:

- `API_URL`
- `INSTANCE_ID`
- `API_TOKEN`
- `SOURCE_GROUP_NAME` or `SOURCE_GROUP_CHAT_ID` (and optional `SOURCE_GROUP_CHAT_IDS` for multiple sources)
- `DESTINATION_GROUP_NAME` or `DESTINATION_GROUP_CHAT_ID`
- `GROUP_LINK_URL`
- `MIRROR_DEBUG`
- `STRIP_LINKS_FROM_TEXT`
- `APPEND_GROUP_LINK_TO_MESSAGES`
- `SCHEDULE_TIMEZONE`
- `SCHEDULE_DB_PATH`
- `PANEL_SECRET_KEY`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`
