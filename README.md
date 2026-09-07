# 🤖 Telegram Join Request Manager Bot

A Telegram bot for managing group join requests.

## ✨ Features

- `/approve` — Auto Approve ON/OFF
- `/addmember 10` — Approve 10 pending requests
- `/addmember 100` — Approve 100 pending requests
- `/addmember 1k` — Approve 1,000 pending requests
- `/addmember 10k` — Approve 10,000 pending requests
- `/stop` — Stop running approval process
- `/remove` — Remove pending requests belonging to deleted accounts
- `/setad Your Ad` — Set advertisement
- `/delad` — Delete advertisement
- MongoDB settings storage
- Heroku worker support

## 🔑 Required Environment Variables

```text
API_ID
API_HASH
BOT_TOKEN
OWNER_ID
MONGO_URL