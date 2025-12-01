import os
import functions_framework
from flask import jsonify
import requests
from dotenv import load_dotenv
from supabase import create_client, Client
from toggl_api.client import get_user_status_string, get_daily_report

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

def send_message(chat_id, text, reply_to_message_id=None):
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN is not set.")
        return None

    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Failed to send message: {e}")
        return None

def edit_message(chat_id, message_id, text):
    if not BOT_TOKEN:
        return

    url = f"{BASE_URL}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to edit message: {e}")

def delete_message(chat_id, message_id):
    if not BOT_TOKEN:
        return

    url = f"{BASE_URL}/deleteMessage"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to delete message: {e}")

@functions_framework.http
def telegram_webhook(request):
    """HTTP Cloud Function."""
    if request.method == 'POST':
        data = request.get_json(silent=True)
        
        # Check if it's a valid message update
        if data and "message" in data:
            chat_id = data["message"]["chat"]["id"]
            sender_id = data["message"].get("from", {}).get("id")
            incoming_message_id = data["message"]["message_id"]
            
            if "text" in data["message"]:
                text = data["message"]["text"].strip()
                print(f"Received message: {text}")
                
                parts = text.split()
                command = parts[0].lower()
                
                if command == "hi":
                    send_message(chat_id, "Hello! I am your Google Cloud Function Telegram bot.", reply_to_message_id=incoming_message_id)
                
                elif command == "/users":
                    if not supabase:
                        send_message(chat_id, "Error: Supabase not configured.", reply_to_message_id=incoming_message_id)
                    else:
                        try:
                            response = supabase.table('Users').select("*").execute()
                            users = response.data
                            if not users:
                                send_message(chat_id, "No users found.", reply_to_message_id=incoming_message_id)
                            else:
                                message = f"👥 Configured Users: ({len(users)})\n\n"
                                for user in users:
                                    user_name = user.get('user_name', 'Unknown User')
                                    # Capitalize the first letter of the username
                                    formatted_user_name = user_name.capitalize()
                                    message += f"- {formatted_user_name}\n"
                                send_message(chat_id, message, reply_to_message_id=incoming_message_id)
                        except Exception as e:
                            print(f"Supabase error: {e}")
                            send_message(chat_id, f"Failed to fetch users: {str(e)}", reply_to_message_id=incoming_message_id)

                elif command == "/status":
                    if not supabase:
                        send_message(chat_id, "Error: Supabase not configured.", reply_to_message_id=incoming_message_id)
                    else:
                        # Send initial processing message
                        loading_msg = send_message(chat_id, "⏳ Processing your request...", reply_to_message_id=incoming_message_id)
                        loading_msg_id = loading_msg.get("result", {}).get("message_id") if loading_msg else None

                        target_name = parts[1].lower() if len(parts) > 1 else "all"
                        
                        try:
                            response = supabase.table('Users').select("*").execute()
                            users = response.data
                            
                            status_messages = []
                            
                            if target_name == "all":
                                # List everyone EXCEPT the sender
                                for user in users:
                                    # Ensure we compare string to string, handling potential None/Int types
                                    user_tele_id = str(user.get('tele_id', ''))
                                    current_sender_id = str(sender_id)
                                    
                                    if user_tele_id != current_sender_id:
                                        user_name = user.get('user_name', 'Unknown')
                                        toggl_token = user.get('toggl_token')
                                        
                                        if toggl_token:
                                            # Get formatted status
                                            status_str = get_user_status_string(user_name.capitalize(), toggl_token)
                                            status_messages.append(status_str)
                            else:
                                # Find specific user
                                found = False
                                for user in users:
                                    if user.get('user_name', '').lower() == target_name:
                                        found = True
                                        user_name = user.get('user_name', 'Unknown')
                                        toggl_token = user.get('toggl_token')
                                        
                                        if toggl_token:
                                            status_str = get_user_status_string(user_name.capitalize(), toggl_token)
                                            status_messages.append(status_str)
                                        else:
                                            status_messages.append(f"⚠️ {user_name.capitalize()} has no Toggl token configured.")
                                        break
                                
                                if not found:
                                    final_msg = f"User '{target_name}' not found."
                                    if loading_msg_id:
                                        delete_message(chat_id, loading_msg_id)
                                    send_message(chat_id, final_msg, reply_to_message_id=incoming_message_id)
                                    return jsonify({"status": "ok"})

                            if status_messages:
                                # Join with double newlines for spacing as per example
                                final_message = "\n\n".join(status_messages)
                            elif target_name == "all":
                                final_message = "No other users found to check."
                            else:
                                final_message = "Status check complete." # Fallback

                            if loading_msg_id:
                                delete_message(chat_id, loading_msg_id)
                            
                            send_message(chat_id, final_message, reply_to_message_id=incoming_message_id)

                        except Exception as e:
                            print(f"Error processing /status: {e}")
                            error_msg = "An error occurred while checking status."
                            if loading_msg_id:
                                delete_message(chat_id, loading_msg_id)
                            send_message(chat_id, error_msg, reply_to_message_id=incoming_message_id)

                elif command == "/today":
                    if not supabase:
                        send_message(chat_id, "Error: Supabase not configured.", reply_to_message_id=incoming_message_id)
                    else:
                        # Send processing message
                        loading_msg = send_message(chat_id, "⏳ Fetching daily report...", reply_to_message_id=incoming_message_id)
                        loading_msg_id = loading_msg.get("result", {}).get("message_id") if loading_msg else None
                        
                        # Parse arguments
                        # Possible: "/today", "/today Tirth", "/today detailed", "/today Tirth detailed", "/today detailed Tirth"
                        args = parts[1:]
                        
                        detailed = False
                        target_name = None
                        
                        # Check for 'detailed' flag
                        if "detailed" in [a.lower() for a in args]:
                            detailed = True
                            # Remove 'detailed' from args to find name
                            args = [a for a in args if a.lower() != "detailed"]
                        
                        if args:
                            target_name = args[0].lower()
                        
                        try:
                            response = supabase.table('Users').select("*").execute()
                            users = response.data
                            
                            target_user = None
                            
                            if target_name:
                                # Search by name
                                for user in users:
                                    if user.get('user_name', '').lower() == target_name:
                                        target_user = user
                                        break
                            else:
                                # Search by sender ID (Self)
                                for user in users:
                                    if str(user.get('tele_id', '')) == str(sender_id):
                                        target_user = user
                                        break
                            
                            if not target_user:
                                msg = f"User '{target_name}' not found." if target_name else "You are not registered in the database."
                                if loading_msg_id:
                                    delete_message(chat_id, loading_msg_id)
                                send_message(chat_id, msg, reply_to_message_id=incoming_message_id)
                            else:
                                # Found user, generate report
                                api_token = target_user.get('toggl_token')
                                user_name = target_user.get('user_name', 'User').capitalize()
                                
                                if not api_token:
                                    msg = f"⚠️ {user_name} has no Toggl token configured."
                                    if loading_msg_id:
                                        delete_message(chat_id, loading_msg_id)
                                    send_message(chat_id, msg, reply_to_message_id=incoming_message_id)
                                else:
                                    # Generate Report
                                    # Defaulting to Asia/Kolkata as requested/implied by context
                                    report = get_daily_report(user_name, api_token, timezone_str='Asia/Kolkata', detailed=detailed)
                                    
                                    if loading_msg_id:
                                        delete_message(chat_id, loading_msg_id)
                                    send_message(chat_id, report, reply_to_message_id=incoming_message_id)

                        except Exception as e:
                            print(f"Error processing /today: {e}")
                            error_msg = "An error occurred while fetching the report."
                            if loading_msg_id:
                                delete_message(chat_id, loading_msg_id)
                            send_message(chat_id, error_msg, reply_to_message_id=incoming_message_id)

        return jsonify({"status": "ok"})
    
    return "Telegram Bot Webhook is active!"
