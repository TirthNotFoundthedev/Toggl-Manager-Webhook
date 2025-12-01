import os
import functions_framework
from flask import jsonify
import requests
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("Warning: SUPABASE_URL or SUPABASE_KEY not set.")

def send_message(chat_id, text):
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN is not set.")
        return

    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to send message: {e}")

@functions_framework.http
def telegram_webhook(request):
    """HTTP Cloud Function."""
    if request.method == 'POST':
        data = request.get_json(silent=True)
        
        # Check if it's a valid message update
        if data and "message" in data:
            chat_id = data["message"]["chat"]["id"]
            
            if "text" in data["message"]:
                text = data["message"]["text"].strip()
                print(f"Received message: {text}")
                
                if text.lower() == "hi":
                    send_message(chat_id, "Hello! I am your Google Cloud Function Telegram bot.")
                elif text.lower() == "/users":
                    if not supabase:
                        send_message(chat_id, "Error: Supabase not configured.")
                    else:
                        try:
                            response = supabase.table('Users').select("*").execute()
                            users = response.data
                            if not users:
                                send_message(chat_id, "No users found.")
                            else:
                                # Customize this formatting based on your table structure
                                message = "Users List:\n"
                                for user in users:
                                    # List only user_name as requested
                                    user_info = f"- {user.get('user_name', 'Unknown User')}"
                                    message += f"{user_info}\n"
                                send_message(chat_id, message)
                        except Exception as e:
                            print(f"Supabase error: {e}")
                            send_message(chat_id, f"Failed to fetch users: {str(e)}")
        
        return jsonify({"status": "ok"})
    
    return "Telegram Bot Webhook is active!"
