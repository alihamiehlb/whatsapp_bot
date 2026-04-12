# WhatsApp group mirror

Re-sends every new message from a **source** WhatsApp group to a **destination** group using [Green API](https://green-api.com/). Messages look like normal sends from your linked number (not “Forwarded”). Optional: strip `http(s)` / `www.` links from text and captions (`STRIP_LINKS_FROM_TEXT` in `config.py`).

---

## Setup

1. Create a Green API instance, link WhatsApp, copy `INSTANCE_ID`, `apiTokenInstance`, and host URL from the console.
2. `pip install -r requirements.txt`
3. Copy `config.example.py` → `config.py` and fill in credentials and **exact** group names as shown in WhatsApp.
4. In the Green API console: enable **incoming messages and files**, and **messages sent from the phone** (otherwise your own test messages in the source group never appear in the queue). **Do not** set a custom webhook if you use this script’s polling.
5. Run: `python index.py`

---

## Files

| File | Role |
|------|------|
| `index.py` | Starts the bot |
| `config.py` | Your secrets and group names (not in git) |
| `bot/forwarder.py` | Green API queue + mirror logic |

**Python 3.10+**

---

## If it “doesn’t work”

- Turn on **incoming messages and files** in the Green API console (required for other people’s messages).
- The linked WhatsApp account must be in **both** groups.
- Run with `MIRROR_DEBUG = True` in `config.py`: you should see `[debug] queue: incomingMessageReceived …` when someone writes in the source group. If you see **nothing**, the queue is empty (wrong instance, custom webhook set, or webhooks disabled).
- If you see `match=False`, the chat id from WhatsApp does not match the resolved source id: set **`SOURCE_GROUP_CHAT_ID`** / **`DESTINATION_GROUP_CHAT_ID`** to the exact `@g.us` values from the Green API group info.
- Watch lines starting with `[API Error]` or `[Mirror]`.
