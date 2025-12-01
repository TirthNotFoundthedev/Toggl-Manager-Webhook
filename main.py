import os
import functions_framework
from flask import jsonify
import requests
from dotenv import load_dotenv
from supabase import create_client, Client
from toggl_api.client import get_user_status_string, get_daily_report, get_leaderboard_report
import json

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

def send_message(chat_id, text, reply_to_message_id=None, reply_markup=None):
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
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
        
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Failed to send message: {e}")
        return None

def edit_message(chat_id, message_id, text, reply_markup=None):
    if not BOT_TOKEN:
        return

    url = f"{BASE_URL}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to edit message: {e}")

def answer_callback_query(callback_query_id, text=None):
    if not BOT_TOKEN:
        return

    url = f"{BASE_URL}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        
    try:
        requests.post(url, json=payload)
    except requests.exceptions.RequestException as e:
        print(f"Failed to answer callback: {e}")

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

def get_user_keyboard(users, command_type):
    """Generates inline keyboard with 'All' and list of users."""
    keyboard = [[{"text": "All 👥", "callback_data": f"cmd:{command_type}:all"}]]
    
    # Add users in rows of 2
    user_buttons = []
    for user in users:
        name = user.get('user_name', 'Unknown').capitalize()
        user_buttons.append({"text": name, "callback_data": f"cmd:{command_type}:{name}"})
    
    # Chunk into rows of 2
    for i in range(0, len(user_buttons), 2):
        keyboard.append(user_buttons[i:i+2])
        
    return {"inline_keyboard": keyboard}

def get_report_keyboard(user_name, current_view):
    """Generates toggle button for report view."""
    if current_view == "normal":
        return {"inline_keyboard": [[{"text": "Show Detailed 📝", "callback_data": f"view:today:{user_name}:detailed"}]]}
    else:
        return {"inline_keyboard": [[{"text": "Show Normal 📊", "callback_data": f"view:today:{user_name}:normal"}]]}

@functions_framework.http
def telegram_webhook(request):
    """HTTP Cloud Function."""
    if request.method == 'POST':
        data = request.get_json(silent=True)
        
        # Handle Callback Queries (Button Clicks)
        if data and "callback_query" in data:
            query = data["callback_query"]
            chat_id = query["message"]["chat"]["id"]
            message_id = query["message"]["message_id"]
            callback_data = query["data"]
            callback_id = query["id"]
            sender_id = query["from"]["id"]
            
            # Acknowledge callback
            answer_callback_query(callback_id)
            
            # Parse Data
            if callback_data.startswith("cmd:"):
                # Format: cmd:status:Tirth or cmd:today:all
                _, cmd_type, target = callback_data.split(":")
                
                # Delete menu message
                delete_message(chat_id, message_id)
                
                # Send "Processing" (new message)
                loading_msg = send_message(chat_id, f"⏳ Fetching {cmd_type} for {target}...")
                loading_msg_id = loading_msg.get("result", {}).get("message_id") if loading_msg else None
                
                # Execute Logic (Reusing the logic is hard without refactoring, so we duplicate slightly for now but keep it clean)
                if cmd_type == "status":
                    # STATUS LOGIC
                    handle_status_request(chat_id, target, sender_id, loading_msg_id)
                elif cmd_type == "today":
                     # TODAY LOGIC
                    handle_today_request(chat_id, target, False, sender_id, loading_msg_id)

            elif callback_data.startswith("view:"):
                # Format: view:today:Tirth:detailed
                _, cmd_type, target, view_mode = callback_data.split(":")
                detailed = (view_mode == "detailed")
                
                # Edit directly, no delete/send new
                handle_today_request(chat_id, target, detailed, sender_id, message_id, is_edit=True)

            return jsonify({"status": "ok"})

        # Handle Text Messages
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
                        # Check arguments
                        if len(parts) > 1:
                            # Specific target
                            target_name = parts[1].lower()
                            loading_msg = send_message(chat_id, f"⏳ Processing status for {target_name}...", reply_to_message_id=incoming_message_id)
                            loading_msg_id = loading_msg.get("result", {}).get("message_id") if loading_msg else None
                            handle_status_request(chat_id, target_name, sender_id, loading_msg_id)
                        else:
                            # Show Menu
                            try:
                                response = supabase.table('Users').select("*").execute()
                                users = response.data
                                keyboard = get_user_keyboard(users, "status")
                                send_message(chat_id, "Select user to check status:", reply_to_message_id=incoming_message_id, reply_markup=keyboard)
                            except Exception as e:
                                send_message(chat_id, f"Error fetching menu: {e}", reply_to_message_id=incoming_message_id)

                elif command == "/today":
                    if not supabase:
                        send_message(chat_id, "Error: Supabase not configured.", reply_to_message_id=incoming_message_id)
                    else:
                        # Parse args for detailed flag or name
                        args = parts[1:]
                        detailed = False
                        target_name = None
                        
                        if "detailed" in [a.lower() for a in args]:
                            detailed = True
                            args = [a for a in args if a.lower() != "detailed"]
                        
                        if args:
                            target_name = args[0].lower()
                        
                        if target_name:
                             # Specific target
                            loading_msg = send_message(chat_id, f"⏳ Processing report for {target_name}...", reply_to_message_id=incoming_message_id)
                            loading_msg_id = loading_msg.get("result", {}).get("message_id") if loading_msg else None
                            handle_today_request(chat_id, target_name, detailed, sender_id, loading_msg_id)
                        else:
                            # Show Menu
                            try:
                                response = supabase.table('Users').select("*").execute()
                                users = response.data
                                keyboard = get_user_keyboard(users, "today")
                                send_message(chat_id, "Select user for daily report:", reply_to_message_id=incoming_message_id, reply_markup=keyboard)
                            except Exception as e:
                                send_message(chat_id, f"Error fetching menu: {e}", reply_to_message_id=incoming_message_id)
                elif command in ["/lb", "/leaderboard"]:
                    if not supabase:
                        send_message(chat_id, "Error: Supabase not configured.", reply_to_message_id=incoming_message_id)
                    else:
                        # Send processing message
                        loading_msg = send_message(chat_id, "⏳ Generating leaderboard...", reply_to_message_id=incoming_message_id)
                        loading_msg_id = loading_msg.get("result", {}).get("message_id") if loading_msg else None
                        
                        try:
                            # Parse arguments
                            args = parts[1:]
                            period = 'daily'
                            offset = 0
                            
                            for arg in args:
                                arg_lower = arg.lower()
                                if arg_lower in ['daily', 'd']:
                                    period = 'daily'
                                elif arg_lower in ['weekly', 'w']:
                                    period = 'weekly'
                                else:
                                    try:
                                        offset = int(arg)
                                    except ValueError:
                                        pass # Ignore unknown args
                            
                            response = supabase.table('Users').select("*").execute()
                            users = response.data
                            
                            if not users:
                                msg = "No users found in database."
                                if loading_msg_id:
                                    delete_message(chat_id, loading_msg_id)
                                send_message(chat_id, msg, reply_to_message_id=incoming_message_id)
                            else:
                                report = get_leaderboard_report(users, period=period, offset=offset, timezone_str='Asia/Kolkata')
                                
                                if loading_msg_id:
                                    delete_message(chat_id, loading_msg_id)
                                send_message(chat_id, report, reply_to_message_id=incoming_message_id)
                                
                        except Exception as e:
                            print(f"Error processing /lb: {e}")
                            error_msg = "An error occurred while generating the leaderboard."
                            if loading_msg_id:
                                delete_message(chat_id, loading_msg_id)
                            send_message(chat_id, error_msg, reply_to_message_id=incoming_message_id)

        return jsonify({"status": "ok"})
    
    return "Telegram Bot Webhook is active!"

# Helper Functions for Logic (Moved out of webhook for cleaner reuse)

def handle_status_request(chat_id, target_name, sender_id, loading_msg_id):
    try:
        response = supabase.table('Users').select("*").execute()
        users = response.data
        
        status_messages = []
        target_name = target_name.lower()
        
        if target_name == "all":
            for user in users:
                user_tele_id = str(user.get('tele_id', ''))
                if user_tele_id != str(sender_id): # Except sender? The button says "All", usually means everyone. But keeping logic consistent.
                     # Wait, if I click "All", I probably want everyone including me? Or sticking to old logic? 
                     # The previous logic was "Except sender". I will keep it for consistency unless asked.
                    user_name = user.get('user_name', 'Unknown')
                    toggl_token = user.get('toggl_token')
                    if toggl_token:
                        status_str = get_user_status_string(user_name.capitalize(), toggl_token)
                        status_messages.append(status_str)
        else:
             # Find specific
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
                status_messages.append(f"User '{target_name}' not found.")

        if not status_messages:
             final_message = "No users found to check."
        else:
            final_message = "\n\n".join(status_messages)

        if loading_msg_id:
            delete_message(chat_id, loading_msg_id)
        
        send_message(chat_id, final_message)

    except Exception as e:
        print(f"Status Error: {e}")
        if loading_msg_id:
            delete_message(chat_id, loading_msg_id)
        send_message(chat_id, "Error checking status.")

def handle_today_request(chat_id, target_name, detailed, sender_id, message_id, is_edit=False):
    try:
        response = supabase.table('Users').select("*").execute()
        users = response.data
        
        target_name = target_name.lower()
        target_user = None
        
        if target_name == "all":
            # Handle "All" for today? The prompt said "button all followed by button for each user".
            # If "All" is clicked, we probably want a summary for everyone.
            # Implementing a loop for ALL users.
            reports = []
            for user in users:
                api = user.get('toggl_token')
                name = user.get('user_name', 'User').capitalize()
                if api:
                    # Force normal view for "All" to avoid spam? Or respect 'detailed'?
                    # Let's respect 'detailed' but it might be huge.
                    rep = get_daily_report(name, api, timezone_str='Asia/Kolkata', detailed=detailed)
                    reports.append(rep)
            
            final_report = ("\n" + "-"*10 + "\n").join(reports)
            if not reports:
                final_report = "No users to report."
            
            # No toggle button for "All" view to keep it simple? Or add one?
            # Let's add one if single user, maybe skip for all?
            keyboard = None 
            
        else:
            # Specific User
            for user in users:
                if user.get('user_name', '').lower() == target_name:
                    target_user = user
                    break
            
            if not target_user:
                final_report = f"User '{target_name}' not found."
                keyboard = None
            else:
                api_token = target_user.get('toggl_token')
                user_name = target_user.get('user_name', 'User').capitalize()
                if not api_token:
                    final_report = f"⚠️ {user_name} has no Toggl token."
                    keyboard = None
                else:
                    final_report = get_daily_report(user_name, api_token, timezone_str='Asia/Kolkata', detailed=detailed)
                    # Add Toggle Button
                    current_view = "detailed" if detailed else "normal"
                    keyboard = get_report_keyboard(user_name, current_view)

        if is_edit:
            # For toggle, we EDIT the message
            edit_message(chat_id, message_id, final_report, reply_markup=keyboard)
        else:
            # For fresh request, we delete loading and send new
            if message_id:
                 delete_message(chat_id, message_id)
            send_message(chat_id, final_report, reply_markup=keyboard)

    except Exception as e:
        print(f"Today Error: {e}")
        if not is_edit and message_id:
             delete_message(chat_id, message_id)
        if is_edit:
             # Can't delete edit, just try to show error
             pass
        else:
             send_message(chat_id, "Error fetching report.")
