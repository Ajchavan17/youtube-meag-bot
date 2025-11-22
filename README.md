# YouTube → MEGA Uploader Bot 🎥➡️☁️

A powerful Telegram bot that:

- Downloads YouTube videos as **MP3**  
- Uploads the MP3 file to a selected **MEGA folder**  
- Fully async, stable, and ready for Railway hosting  
- Includes interactive folder selection  

---

## 🚀 Features

### ✔️ Download MP3 using yt-dlp  
### ✔️ Upload to any MEGA folder  
### ✔️ Interactive folder selection  
### ✔️ Clean logging and professional error messages  
### ✔️ Free hosting on Railway  
### ✔️ Command:  


---

## 🛠️ Tech Stack
- Python 3.11  
- python-telegram-bot  
- yt-dlp  
- mega.py (logging in with email/password)  
- Async execution  
- Railway deployment ready  

---

## 📁 Project Structure
project/
│── bot_logic.py
│── config.py (ignored in git)
│── requirements.txt
│── README.md
│── .gitignore


---

## 🔧 Local Setup

git clone https://github.com/
<your-username>/<repo>.git
cd repo

python -m venv .venv
source .venv/Scripts/activate # Windows
pip install -r requirements.txt
python bot_logic.py


---

## 🔐 Environment Variables (Railway)

Add these inside Railway → Variables:

| Variable | Purpose |
|----------|----------|
| `TELEGRAM_BOT_TOKEN` | Your bot token |
| `MEGA_EMAIL` | MEGA login email |
| `MEGA_PASSWORD` | MEGA login password |

---

## 🚀 Deploy on Railway

1. Push your code to GitHub  
2. Open **https://railway.app**  
3. Create New → Deploy from Repository  
4. Add environment variables  
5. Deploy  
6. Railway auto-wakes when bot receives a message  

---

## 🧑‍💻 Author
Ajit Chavan

---

## ⭐ Star the repo if you like it!

