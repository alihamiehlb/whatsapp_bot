# ============================================================
# config.example.py - Central configuration for the WhatsApp bot
# ============================================================
# Rename this file to config.py and set your credentials.

# ---- Green API Credentials ----
# Get these from your dashboard at https://green-api.com
API_URL                = 'https://api.greenapi.com'
INSTANCE_ID            = ''
API_TOKEN              = ''

# ---- Groups (pick ONE way: names OR chat ids) ----
SOURCE_GROUP_NAME       = ''   # exact WhatsApp group title, or leave blank if using id below
DESTINATION_GROUP_NAME  = ''

# Paste JIDs from Green API (group info / console) if name matching fails:
SOURCE_GROUP_CHAT_ID       = ''   # e.g. 120363123456789012@g.us
DESTINATION_GROUP_CHAT_ID  = ''

# Prints each incoming/outgoing message event and whether chatId matches source (turn off once fixed)
MIRROR_DEBUG = True

# Remove http(s) and www.… links from mirrored text and image/video captions (plain text only)
STRIP_LINKS_FROM_TEXT = True
