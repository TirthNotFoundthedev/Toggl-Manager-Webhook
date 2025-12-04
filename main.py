import os
import functions_framework
from flask import jsonify, render_template_string
import requests
from dotenv import load_dotenv
from supabase import create_client, Client
from toggl_api.client import get_user_status_string, get_daily_report, get_leaderboard_report
from wake_manager.actions import perform_wake, perform_wake_all, handle_wake_reply
import json
from datetime import datetime, timedelta
import pytz
import secrets
import string

load_dotenv()

COMMANDS = {
    "start": {
        "description": "Start the bot and see available commands.",
        "usage": "/start"
    },
    "help": {
        "description": "Get help for a specific command.",
        "usage": "/help [command]"
    },
    "status": {
        "description": "Check if a user (or everyone) is currently tracking time.",
        "usage": "/status [user]\nExamples:\n`/status` - Menu\n`/status Tirth` - Check Tirth"
    },
    "today": {
        "description": "Get a daily report of time tracked.",
        "usage": "/today [user] [detailed]\nExamples:\n`/today` - Menu\n`/today Tirth` - Report for Tirth\n`/today Tirth detailed` - Detailed report"
    },
    "leaderboard": {
        "description": "View the leaderboard for time tracked.",
        "usage": "/leaderboard [daily/weekly] [offset]\nExamples:\n`/leaderboard` - Default (Daily)\n`/leaderboard weekly` - This week\n`/leaderboard daily -1` - Yesterday"
    },
    "users": {
        "description": "List all configured users.",
        "usage": "/users"
    },
    "wake": {
        "description": "Nudge a user to start working if they aren't tracking time.",
        "usage": "/wake [user] [message]\nExamples:\n`/wake` - Menu\n`/wake Tirth` - Wake Tirth\n`/wake Tirth Get back to work!` - Custom msg"
    }
}

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_USERNAME = "toggleautoReporter_bot" # As provided
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

def get_leaderboard_keyboard(period, offset):
    """Generates navigation buttons for leaderboard with smart context switching."""
    
    # Logic for Toggle:
    # Daily -> Weekly: Find the week containing the current daily date.
    # Weekly -> Daily: Find the Monday of the current week.
    
    timezone_str = 'Asia/Kolkata'
    tz = pytz.timezone(timezone_str)
    # Normalize 'now' to midnight to ensure consistent day math
    now = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)

    if period == 'daily':
        # Switching TO Weekly
        # 1. Determine the specific date we are currently looking at
        focus_date = now + timedelta(days=offset)
        
        # 2. Determine the Monday of the week that date falls in
        focus_week_start = focus_date - timedelta(days=focus_date.weekday())
        
        # 3. Determine the Monday of the "Current" real-world week
        current_real_week_start = now - timedelta(days=now.weekday())
        
        # 4. Calculate difference in weeks
        # (Target Monday - Current Monday) / 7 days
        new_offset = (focus_week_start - current_real_week_start).days // 7
        
        toggle_text = "Switch to Weekly 📅"
        toggle_period = 'weekly'
        
    else: # period == 'weekly'
        # Switching TO Daily
        # 1. Determine the Monday of the week we are looking at
        # Start with current real week Monday
        current_real_week_start = now - timedelta(days=now.weekday())
        # Apply offset
        focus_week_start = current_real_week_start + timedelta(weeks=offset)
        
        # 2. Calculate difference in days between that Monday and "Now"
        new_offset = (focus_week_start - now).days
        
        toggle_text = "Switch to Daily 📅"
        toggle_period = 'daily'
    
    keyboard = [
        [
            {"text": "⬅️ Prev", "callback_data": f"lb:{period}:{offset-1}"},
            {"text": toggle_text, "callback_data": f"lb:{toggle_period}:{new_offset}"},
            {"text": "Next ➡️", "callback_data": f"lb:{period}:{offset+1}"}
        ]
    ]
    return {"inline_keyboard": keyboard}

# --- Auth Helpers ---
def handle_login_request(data):
    username = data.get('username', '').strip().lower().replace('@', '')
    if not username: 
        return jsonify({'status': 'error', 'message': 'Username required'}), 400
    
    if not supabase:
        return jsonify({'status': 'error', 'message': 'Database not configured'}), 500

    try:
        # Try to find user (case insensitive manually if ilike fails, but ilike is standard)
        res = supabase.table('Users').select("*").ilike('user_name', username).execute()
        user = res.data[0] if res.data else None
    except Exception as e:
        print(f"DB Error: {e}")
        return jsonify({'status': 'error', 'message': 'Database error'}), 500
    
    if not user: 
        return jsonify({'status': 'error', 'message': 'User not found'}), 404
    
    # Generate Code
    code = ''.join(secrets.choice(string.digits) for _ in range(6))
    # Expire in 10 mins
    expires = (datetime.now(pytz.utc) + timedelta(minutes=10)).isoformat()
    
    # Update DB (using wake_cooldown hack)
    meta = user.get('wake_cooldown', {})
    # Handle if it's string or None
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except:
            meta = {}
    if not isinstance(meta, dict): meta = {}
    
    meta['auth'] = {'code': code, 'expires': expires}
    
    try:
        supabase.table('Users').update({'wake_cooldown': meta}).eq('id', user['id']).execute()
    except Exception as e:
        return jsonify({'status': 'error', 'message': 'Failed to save code'}), 500
    
    # Send Telegram
    msg = f"🔐 *Login Verification*\n\nYour code is: `{code}`\nExpires in 10 minutes."
    send_message(user['tele_id'], msg)
    
    return jsonify({'status': 'ok'})

def handle_verify_request(data):
    username = data.get('username', '').strip().lower().replace('@', '')
    code = data.get('code', '').strip()
    
    if not username or not code:
        return jsonify({'status': 'error', 'message': 'Missing fields'}), 400

    try:
        res = supabase.table('Users').select("*").ilike('user_name', username).execute()
        user = res.data[0] if res.data else None
    except Exception:
        return jsonify({'status': 'error', 'message': 'Database error'}), 500
        
    if not user: return jsonify({'status': 'error', 'message': 'User not found'}), 404
    
    meta = user.get('wake_cooldown', {})
    if isinstance(meta, str):
        try: meta = json.loads(meta)
        except: meta = {}
    
    auth = meta.get('auth')
    if not auth: return jsonify({'status': 'error', 'message': 'No pending login'}), 400
    
    # Check Code
    if auth.get('code') != code:
        return jsonify({'status': 'error', 'message': 'Invalid code'}), 400
        
    # Check Expiry
    expires_str = auth.get('expires')
    if not expires_str: return jsonify({'status': 'error', 'message': 'Invalid expiry'}), 400
    
    expires = datetime.fromisoformat(expires_str)
    if datetime.now(pytz.utc) > expires:
        return jsonify({'status': 'error', 'message': 'Code expired'}), 400
        
    # Success - Clear Code
    del meta['auth']
    try:
        supabase.table('Users').update({'wake_cooldown': meta}).eq('id', user['id']).execute()
    except: 
        pass # Non-critical
    
    return jsonify({'status': 'ok', 'token': 'dummy_token_session', 'username': user['user_name']})


@functions_framework.http
def telegram_webhook(request):
    """HTTP Cloud Function."""
    
    # 1. Handle API/Login Logic (POST with specific actions)
    if request.method == 'POST':
        data = request.get_json(silent=True)
        if data:
            # API Routing
            if 'action' in data:
                action = data['action']
                if action == 'request_code':
                    return handle_login_request(data)
                elif action == 'verify_code':
                    return handle_verify_request(data)
            
            # Telegram Logic (Webhook)
            # (Only if it looks like a telegram update)
            if "update_id" in data:
                # Handle Callback Queries (Button Clicks)
                if "callback_query" in data:
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
                        
                        # Execute Logic
                        if cmd_type == "status":
                            handle_status_request(chat_id, target, sender_id, loading_msg_id)
                        elif cmd_type == "today":
                            handle_today_request(chat_id, target, False, sender_id, loading_msg_id)
                        elif cmd_type == "wake":
                            # Wake Logic
                            sender_name = query["from"].get("first_name", "Unknown")
                            delete_message(chat_id, loading_msg_id) # Remove "Processing..."

                            if target == "all":
                                # For "All", we typically don't do custom message per user, just run it.
                                result = perform_wake_all(supabase, sender_id, sender_name, custom_message="", command_msg_id=message_id)
                                send_message(chat_id, result)
                            else:
                                result = perform_wake(supabase, sender_id, sender_name, target, custom_message="", command_msg_id=message_id)
                                send_message(chat_id, result)

                    elif callback_data.startswith("view:"):
                        # Format: view:today:Tirth:detailed
                        _, cmd_type, target, view_mode = callback_data.split(":")
                        detailed = (view_mode == "detailed")
                        
                        # Edit directly
                        handle_today_request(chat_id, target, detailed, sender_id, message_id, is_edit=True)

                    elif callback_data.startswith("lb:"):
                        # Format: lb:daily:-1
                        parts = callback_data.split(":")
                        period = parts[1]
                        try:
                            offset = int(parts[2])
                        except:
                            offset = 0
                        
                        # Edit leaderboard directly (navigation)
                        handle_leaderboard_request(chat_id, period, offset, message_id, is_edit=True)

                    return jsonify({"status": "ok"})

                # Handle Text Messages
                if "message" in data:
                    chat_id = data["message"]["chat"]["id"]
                    sender_id = data["message"].get("from", {}).get("id")
                    incoming_message_id = data["message"]["message_id"]
                    
                    if "text" in data["message"]:
                        text = data["message"]["text"].strip()
                        print(f"Received message: {text}")
                        
                        # Check for Reply to Wake Message
                        reply_to = data["message"].get("reply_to_message")
                        if reply_to:
                            reply_msg_id = reply_to["message_id"]
                            sender_name = data["message"].get("from", {}).get("first_name", "Unknown")
                            
                            # Try to handle as wake reply
                            if handle_wake_reply(supabase, reply_msg_id, text, sender_name):
                                send_message(chat_id, "✅ Wake reply forwarded successfully!", reply_to_message_id=incoming_message_id)
                                return jsonify({"status": "ok"}) # Handled, exit
                        
                        parts = text.split()
                        command = parts[0].lower()
                        if "@" in command:
                            command = command.split("@")[0]
                        
                        if command == "/start":
                            # Handle deep linking parameters (e.g. /start status)
                            if len(parts) > 1:
                                param = parts[1].lower()
                                # Map param to command
                                if param == "status":
                                    # Trigger status immediately
                                    handle_status_request(chat_id, "all", sender_id, None)
                                elif param == "leaderboard":
                                    handle_leaderboard_request(chat_id, 'daily', 0, None, is_edit=False, reply_to_id=incoming_message_id)
                                else:
                                    send_message(chat_id, f"Unknown parameter: {param}")
                            else:
                                welcome_text = "👋 *Welcome to the Toggl Status Bot!* \n\nHere are the available commands:\n\n"
                                for cmd, details in COMMANDS.items():
                                    welcome_text += f"/{cmd} - {details['description']}\n"
                                welcome_text += "\nType `/help <command>` for more details."
                                send_message(chat_id, welcome_text, reply_to_message_id=incoming_message_id)

                        elif command == "/help":
                            args = parts[1:]
                            if not args:
                                help_text = "📚 *Available Commands:*\n\n"
                                for cmd, details in COMMANDS.items():
                                    help_text += f"/{cmd} - {details['description']}\n"
                                help_text += "\nUsage: `/help <command_name>`"
                                send_message(chat_id, help_text, reply_to_message_id=incoming_message_id)
                            else:
                                cmd_name = args[0].replace("/", "").lower()
                                if cmd_name in COMMANDS:
                                    details = COMMANDS[cmd_name]
                                    detail_text = f"ℹ️ *Help for /{cmd_name}*\n\n"
                                    detail_text += f"📝 *Description:* {details['description']}\n"
                                    detail_text += f"⌨️ *Usage:* `{details['usage']}`"
                                    send_message(chat_id, detail_text, reply_to_message_id=incoming_message_id)
                                else:
                                    send_message(chat_id, f"❌ Command '/{cmd_name}' not found.", reply_to_message_id=incoming_message_id)
                        
                        elif command == "/users":
                            # ... (existing /users logic same as before) ...
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
                            # ... (existing /status logic) ...
                            if not supabase:
                                send_message(chat_id, "Error: Supabase not configured.", reply_to_message_id=incoming_message_id)
                            else:
                                if len(parts) > 1:
                                    target_name = parts[1].lower()
                                    loading_msg = send_message(chat_id, f"⏳ Processing status for {target_name}...", reply_to_message_id=incoming_message_id)
                                    loading_msg_id = loading_msg.get("result", {}).get("message_id") if loading_msg else None
                                    handle_status_request(chat_id, target_name, sender_id, loading_msg_id)
                                else:
                                    try:
                                        response = supabase.table('Users').select("*").execute()
                                        users = response.data
                                        keyboard = get_user_keyboard(users, "status")
                                        send_message(chat_id, "Select user to check status:", reply_to_message_id=incoming_message_id, reply_markup=keyboard)
                                    except Exception as e:
                                        send_message(chat_id, f"Error fetching menu: {e}", reply_to_message_id=incoming_message_id)

                        elif command == "/today":
                            # ... (existing /today logic) ...
                            if not supabase:
                                send_message(chat_id, "Error: Supabase not configured.", reply_to_message_id=incoming_message_id)
                            else:
                                args = parts[1:]
                                detailed = False
                                target_name = None
                                if "detailed" in [a.lower() for a in args]:
                                    detailed = True
                                    args = [a for a in args if a.lower() != "detailed"]
                                if args:
                                    target_name = args[0].lower()
                                
                                if target_name:
                                    loading_msg = send_message(chat_id, f"⏳ Processing report for {target_name}...", reply_to_message_id=incoming_message_id)
                                    loading_msg_id = loading_msg.get("result", {}).get("message_id") if loading_msg else None
                                    handle_today_request(chat_id, target_name, detailed, sender_id, loading_msg_id)
                                else:
                                    try:
                                        response = supabase.table('Users').select("*").execute()
                                        users = response.data
                                        keyboard = get_user_keyboard(users, "today")
                                        send_message(chat_id, "Select user for daily report:", reply_to_message_id=incoming_message_id, reply_markup=keyboard)
                                    except Exception as e:
                                        send_message(chat_id, f"Error fetching menu: {e}", reply_to_message_id=incoming_message_id)

                        elif command == "/wake":
                            if not supabase:
                                send_message(chat_id, "Error: Supabase not configured.", reply_to_message_id=incoming_message_id)
                            else:
                                # Parse: /wake <name> <custom message...>
                                args = parts[1:]
                                if args:
                                    target_name = args[0].lower()
                                    custom_message = " ".join(args[1:]) if len(args) > 1 else ""
                                    
                                    loading_msg = send_message(chat_id, f"🔔 Nudging {target_name}...", reply_to_message_id=incoming_message_id)
                                    loading_msg_id = loading_msg.get("result", {}).get("message_id") if loading_msg else None
                                    
                                    sender_name = data["message"].get("from", {}).get("first_name", "Unknown")
                                    
                                    if target_name == "all":
                                        result = perform_wake_all(supabase, sender_id, sender_name, custom_message, incoming_message_id)
                                    else:
                                        result = perform_wake(supabase, sender_id, sender_name, target_name, custom_message, incoming_message_id)
                                        
                                    if loading_msg_id:
                                        delete_message(chat_id, loading_msg_id)
                                    send_message(chat_id, result, reply_to_message_id=incoming_message_id)
                                else:
                                    # Show Menu
                                    try:
                                        response = supabase.table('Users').select("*").execute()
                                        users = response.data
                                        keyboard = get_user_keyboard(users, "wake")
                                        send_message(chat_id, "Who needs to wake up? 🔔", reply_to_message_id=incoming_message_id, reply_markup=keyboard)
                                    except Exception as e:
                                        send_message(chat_id, f"Error fetching menu: {e}", reply_to_message_id=incoming_message_id)

                        elif command in ["/lb", "/leaderboard"]:
                            if not supabase:
                                send_message(chat_id, "Error: Supabase not configured.", reply_to_message_id=incoming_message_id)
                            else:
                                # Send processing message
                                loading_msg = send_message(chat_id, "⏳ Generating leaderboard...", reply_to_message_id=incoming_message_id)
                                loading_msg_id = loading_msg.get("result", {}).get("message_id") if loading_msg else None
                                
                                # Parse arguments (Daily/Weekly, offset)
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
                                            pass

                                # Use new handler function
                                handle_leaderboard_request(chat_id, period, offset, loading_msg_id, is_edit=False, reply_to_id=incoming_message_id)

                return jsonify({"status": "ok"})
    
    # HTML Landing Page
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Toggl Bot</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            background-color: #1a1a1a;
            color: #e0e0e0;
            font-family: 'Courier New', Courier, monospace;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            overflow: hidden;
            position: relative;
        }
        .background {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(to bottom, #0f0c29, #302b63, #24243e);
            z-index: -1;
        }
        .star {
            position: absolute;
            width: 4px;
            height: 4px;
            background: #fff;
            opacity: 0.6;
            animation: twinkle 4s infinite ease-in-out;
        }
        @keyframes twinkle {
            0%, 100% { opacity: 0.3; transform: scale(1); }
            50% { opacity: 1; transform: scale(1.2); }
        }
        .container {
            text-align: center;
            background: rgba(0, 0, 0, 0.7);
            padding: 40px;
            border: 4px solid #4a4a4a;
            border-radius: 4px;
            box-shadow: 0 0 20px rgba(0,0,0,0.8);
            max-width: 400px;
            width: 90%;
        }
        h1 {
            font-size: 2.5rem;
            margin-bottom: 20px;
            color: #50c878;
            text-shadow: 2px 2px 0px #000;
        }
        .input-group {
            margin-bottom: 15px;
            text-align: left;
        }
        input {
            width: 100%;
            padding: 10px;
            margin-top: 5px;
            background: #222;
            border: 1px solid #555;
            color: #fff;
            font-family: inherit;
            font-size: 1rem;
            box-sizing: border-box;
        }
        .btn {
            display: inline-block;
            width: 100%;
            color: #fff;
            padding: 12px;
            font-weight: bold;
            border: 2px solid #fff;
            background: rgba(255, 255, 255, 0.1);
            cursor: pointer;
            text-transform: uppercase;
            margin-top: 10px;
            transition: 0.3s;
        }
        .btn:hover {
            background: #fff;
            color: #000;
        }
        .hidden { display: none; }
        .error { color: #ff5555; margin-top: 10px; font-size: 0.9rem; }
        
        /* Bot Buttons */
        .bot-links {
            margin-top: 30px;
            border-top: 1px solid #444;
            padding-top: 20px;
        }
        .bot-btn {
            display: block;
            margin: 10px 0;
            padding: 10px;
            background: #4078c0;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 0.9rem;
        }
        .bot-btn:hover { opacity: 0.9; }

        /* Dashboard */
        #dashboard-view {
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="background"></div>

    <div class="container" id="login-view">
        <h1>🔐 Login</h1>
        <p>Enter your Telegram username to receive a verification code.</p>
        
        <div id="step-1">
            <div class="input-group">
                <label>Telegram Username</label>
                <input type="text" id="username" placeholder="e.g. Tirth">
            </div>
            <button class="btn" onclick="requestCode()">Get Code</button>
        </div>

        <div id="step-2" class="hidden">
            <div class="input-group">
                <label>Verification Code</label>
                <input type="text" id="code" placeholder="123456">
            </div>
            <button class="btn" onclick="verifyCode()">Login</button>
            <p style="font-size: 0.8rem; margin-top:10px; cursor:pointer; color:#aaa;" onclick="resetLogin()">Back</p>
        </div>

        <p class="error" id="error-msg"></p>

        <div class="bot-links">
            <h3>🤖 Quick Actions</h3>
            <a href="https://t.me/toggleautoReporter_bot?start=status" target="_blank" class="bot-btn">📊 Check Status</a>
            <a href="https://t.me/toggleautoReporter_bot?start=leaderboard" target="_blank" class="bot-btn">🏆 Leaderboard</a>
        </div>
    </div>

    <div class="container hidden" id="dashboard-view">
        <h1>👋 Welcome!</h1>
        <p id="welcome-msg">You are logged in.</p>
        <p style="color: #888; font-size: 0.9rem;">(Dashboard under construction)</p>
        <button class="btn" onclick="logout()">Logout</button>
    </div>

    <script>
        // Stars
        const bg = document.querySelector('.background');
        for(let i=0; i<50; i++) {
            let star = document.createElement('div');
            star.className = 'star';
            star.style.left = Math.random() * 100 + '%';
            star.style.top = Math.random() * 100 + '%';
            star.style.animationDelay = Math.random() * 5 + 's';
            bg.appendChild(star);
        }

        // Logic
        function checkSession() {
            const token = localStorage.getItem('token');
            const user = localStorage.getItem('username');
            if (token) {
                document.getElementById('login-view').classList.add('hidden');
                document.getElementById('dashboard-view').classList.remove('hidden');
                document.getElementById('welcome-msg').innerText = `You are logged in as ${user}.`;
            }
        }
        checkSession();

        async function requestCode() {
            const username = document.getElementById('username').value;
            const errorEl = document.getElementById('error-msg');
            errorEl.innerText = "";
            
            if(!username) { errorEl.innerText = "Please enter username."; return; }

            try {
                const res = await fetch('', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: 'request_code', username: username})
                });
                const data = await res.json();
                
                if(data.status === 'ok') {
                    document.getElementById('step-1').classList.add('hidden');
                    document.getElementById('step-2').classList.remove('hidden');
                } else {
                    errorEl.innerText = data.message || "Error requesting code.";
                }
            } catch(e) {
                errorEl.innerText = "Network error.";
            }
        }

        async function verifyCode() {
            const username = document.getElementById('username').value;
            const code = document.getElementById('code').value;
            const errorEl = document.getElementById('error-msg');
            errorEl.innerText = "";

            try {
                const res = await fetch('', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: 'verify_code', username: username, code: code})
                });
                const data = await res.json();
                
                if(data.status === 'ok') {
                    localStorage.setItem('token', data.token);
                    localStorage.setItem('username', data.username);
                    checkSession();
                } else {
                    errorEl.innerText = data.message || "Invalid code.";
                }
            } catch(e) {
                errorEl.innerText = "Network error.";
            }
        }
        
        function resetLogin() {
             document.getElementById('step-1').classList.remove('hidden');
             document.getElementById('step-2').classList.add('hidden');
             document.getElementById('error-msg').innerText = "";
        }

        function logout() {
            localStorage.removeItem('token');
            localStorage.removeItem('username');
            location.reload();
        }
    </script>
</body>
</html>
    ""
    return render_template_string(html_content)

# ... (handle_status_request and handle_today_request stay here) ...

def handle_leaderboard_request(chat_id, period, offset, message_id, is_edit=False, reply_to_id=None):
    try:
        if is_edit:
            edit_message(chat_id, message_id, "⏳ Updating...")
            
        response = supabase.table('Users').select("*").execute()
        users = response.data
        
        if not users:
            msg = "No users found in database."
            if is_edit:
                # Can't delete/resend nicely here without context, just edit text
                 edit_message(chat_id, message_id, msg)
            else:
                if message_id: delete_message(chat_id, message_id)
                send_message(chat_id, msg, reply_to_message_id=reply_to_id)
            return

        # Generate Report
        report = get_leaderboard_report(users, period=period, offset=offset, timezone_str='Asia/Kolkata')
        
        # Generate Navigation Keyboard
        keyboard = get_leaderboard_keyboard(period, offset)
        
        if is_edit:
            edit_message(chat_id, message_id, report, reply_markup=keyboard)
        else:
            if message_id: delete_message(chat_id, message_id)
            send_message(chat_id, report, reply_to_message_id=reply_to_id, reply_markup=keyboard)

    except Exception as e:
        print(f"Leaderboard Error: {e}")
        error_msg = "An error occurred while generating the leaderboard."
        if is_edit:
            edit_message(chat_id, message_id, error_msg)
        else:
            if message_id: delete_message(chat_id, message_id)
            send_message(chat_id, error_msg, reply_to_message_id=reply_to_id)


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
        if is_edit:
            edit_message(chat_id, message_id, "⏳ Updating...")
            
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