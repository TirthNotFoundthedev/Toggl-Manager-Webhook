import os
import functions_framework
from flask import jsonify, render_template_string
import requests
from dotenv import load_dotenv
from supabase import create_client, Client
from toggl_api.client import get_user_status_string, get_daily_report, get_leaderboard_report, sync_user_data
from wake_manager.actions import perform_wake, perform_wake_all, handle_wake_reply
import json
from datetime import datetime, timedelta
import pytz

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
    },
    "settings": {
        "description": "Manage your profile (name and Toggl token).",
        "usage": "/settings"
    }
}

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

def get_report_keyboard(user_name, current_view, target_date_str):
    """Generates toggle button and navigation for report view."""
    # Ensure we have a date object
    tz = pytz.timezone('Asia/Kolkata')
    if not target_date_str:
        current_dt = datetime.now(tz)
        target_date_str = current_dt.strftime('%Y-%m-%d')
    else:
        try:
            current_dt = datetime.strptime(target_date_str, '%Y-%m-%d')
        except ValueError:
            current_dt = datetime.now(tz)
            target_date_str = current_dt.strftime('%Y-%m-%d')

    prev_date = (current_dt - timedelta(days=1)).strftime('%Y-%m-%d')
    next_date = (current_dt + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Toggle View Button
    if current_view == "normal":
        view_btn = {"text": "Show Detailed 📝", "callback_data": f"view:today:{user_name}:detailed:{target_date_str}"}
    else:
        view_btn = {"text": "Show Normal 📊", "callback_data": f"view:today:{user_name}:normal:{target_date_str}"}
    
    # Navigation Row
    nav_row = [
        {"text": "⬅️", "callback_data": f"view:today:{user_name}:{current_view}:{prev_date}"},
        {"text": "Refresh 🔄", "callback_data": f"view:today:{user_name}:{current_view}:{target_date_str}"},
        {"text": "➡️", "callback_data": f"view:today:{user_name}:{current_view}:{next_date}"}
    ]

    return {"inline_keyboard": [[view_btn], nav_row]}

def get_leaderboard_keyboard(period, target_date_str):
    """Generates navigation buttons for leaderboard with absolute date logic."""
    tz = pytz.timezone('Asia/Kolkata')
    
    if not target_date_str:
        current_dt = datetime.now(tz)
        target_date_str = current_dt.strftime('%Y-%m-%d')
    else:
        try:
            current_dt = datetime.strptime(target_date_str, '%Y-%m-%d')
        except ValueError:
            current_dt = datetime.now(tz)
            target_date_str = current_dt.strftime('%Y-%m-%d')

    # Calculate Prev/Next based on period
    if period == 'daily':
        prev_date = (current_dt - timedelta(days=1)).strftime('%Y-%m-%d')
        next_date = (current_dt + timedelta(days=1)).strftime('%Y-%m-%d')
        toggle_text = "Switch to Weekly 📅"
        toggle_period = 'weekly'
    else: # weekly
        prev_date = (current_dt - timedelta(weeks=1)).strftime('%Y-%m-%d')
        next_date = (current_dt + timedelta(weeks=1)).strftime('%Y-%m-%d')
        toggle_text = "Switch to Daily 📅"
        toggle_period = 'daily'
    
    # Navigation Row
    nav_row = [
        {"text": "⬅️", "callback_data": f"lb:{period}:{prev_date}"},
        {"text": toggle_text, "callback_data": f"lb:{toggle_period}:{target_date_str}"},
        {"text": "➡️", "callback_data": f"lb:{period}:{next_date}"}
    ]
    
    # Refresh Row
    refresh_row = [
         {"text": "Refresh 🔄", "callback_data": f"lb:{period}:{target_date_str}"}
    ]
    
    return {"inline_keyboard": [nav_row, refresh_row]}

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
                
                # Execute Logic
                if cmd_type == "status":
                    handle_status_request(chat_id, target, sender_id, loading_msg_id)
                elif cmd_type == "today":
                    # Default to today
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
                # Format: view:today:Tirth:detailed:YYYY-MM-DD
                parts = callback_data.split(":")
                # view:today:Tirth:detailed:2025-01-01
                cmd_type = parts[1]
                target = parts[2]
                view_mode = parts[3]
                detailed = (view_mode == "detailed")
                
                target_date_str = None
                if len(parts) > 4:
                    target_date_str = parts[4]
                
                # Edit directly
                handle_today_request(chat_id, target, detailed, sender_id, message_id, is_edit=True, target_date_str=target_date_str)

            elif callback_data.startswith("lb:"):
                # Format: lb:daily:YYYY-MM-DD
                parts = callback_data.split(":")
                period = parts[1]
                target_date_str = None
                if len(parts) > 2:
                    target_date_str = parts[2]
                
                # Edit leaderboard directly (navigation)
                handle_leaderboard_request(chat_id, period, target_date_str, message_id, is_edit=True)

            elif callback_data == "reg:new":
                # Prompt for name
                delete_message(chat_id, message_id)
                send_message(chat_id, "Please reply to this message with your display name for the bot. (Max 15 chars)", 
                             reply_markup={"force_reply": True})

            elif callback_data == "settings:name":
                # Prompt for name
                delete_message(chat_id, message_id)
                send_message(chat_id, "Please reply to this message with your new display name. (Max 15 chars)", 
                             reply_markup={"force_reply": True})
                             
            elif callback_data == "settings:token":
                # Prompt for token
                delete_message(chat_id, message_id)
                send_message(chat_id, "Please reply to this message with your new Toggl API Token. You can find it in your Toggl Profile Settings.", 
                             reply_markup={"force_reply": True})

            return jsonify({"status": "ok"})

        # Handle Text Messages
        if data and "message" in data:
            chat_id = data["message"]["chat"]["id"]
            sender_id = data["message"].get("from", {}).get("id")
            incoming_message_id = data["message"]["message_id"]
            
            if "text" in data["message"]:
                text = data["message"]["text"].strip()
                print(f"Received message: {text}")
                
                # Check for Reply
                reply_to = data["message"].get("reply_to_message")
                if reply_to:
                    reply_msg_id = reply_to["message_id"]
                    reply_to_text = reply_to.get("text", "")
                    sender_name_tele = data["message"].get("from", {}).get("first_name", "Unknown")
                    
                    # 1. Handle Settings/Registration Replies
                    if "display name" in reply_to_text:
                        handle_name_update(chat_id, sender_id, text, incoming_message_id)
                        return jsonify({"status": "ok"})
                    elif "Toggl API Token" in reply_to_text:
                        handle_token_update(chat_id, sender_id, text, incoming_message_id)
                        return jsonify({"status": "ok"})

                    # 2. Try to handle as wake reply
                    if handle_wake_reply(supabase, reply_msg_id, text, sender_name_tele):
                        send_message(chat_id, "✅ Wake reply forwarded successfully!", reply_to_message_id=incoming_message_id)
                        return jsonify({"status": "ok"}) # Handled, exit
                
                parts = text.split()
                command = parts[0].lower()
                if "@" in command:
                    command = command.split("@")[0]
                
                if command == "/start":
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

                elif command == "/settings":
                    if not supabase:
                        send_message(chat_id, "Error: Supabase not configured.", reply_to_message_id=incoming_message_id)
                    else:
                        handle_settings_request(chat_id, sender_id, incoming_message_id)

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
                    if not supabase:
                        send_message(chat_id, "Error: Supabase not configured.", reply_to_message_id=incoming_message_id)
                    else:
                        args = parts[1:]
                        detailed = False
                        target_name = None
                        target_date_str = None
                        
                        # Parse args
                        cleaned_args = []
                        tz = pytz.timezone('Asia/Kolkata')
                        
                        for arg in args:
                            arg_lower = arg.lower()
                            if arg_lower == "detailed":
                                detailed = True
                            else:
                                try:
                                    # Try to parse as integer offset and convert to date immediately
                                    offset = int(arg)
                                    target_date = datetime.now(tz) + timedelta(days=offset)
                                    target_date_str = target_date.strftime('%Y-%m-%d')
                                except ValueError:
                                    # Assume it's a name if not int and not reserved word
                                    cleaned_args.append(arg)
                        
                        if cleaned_args:
                            target_name = cleaned_args[0].lower()
                        
                        if target_name:
                            loading_msg = send_message(chat_id, f"⏳ Processing report for {target_name}...", reply_to_message_id=incoming_message_id)
                            loading_msg_id = loading_msg.get("result", {}).get("message_id") if loading_msg else None
                            handle_today_request(chat_id, target_name, detailed, sender_id, loading_msg_id, target_date_str=target_date_str)
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
                        target_date_str = None
                        
                        tz = pytz.timezone('Asia/Kolkata')
                        
                        for arg in args:
                            arg_lower = arg.lower()
                            if arg_lower in ['daily', 'd']:
                                period = 'daily'
                            elif arg_lower in ['weekly', 'w']:
                                period = 'weekly'
                            else:
                                try:
                                    offset = int(arg)
                                    target_date = datetime.now(tz) + timedelta(days=offset)
                                    target_date_str = target_date.strftime('%Y-%m-%d')
                                except ValueError:
                                    pass

                        # Use new handler function
                        handle_leaderboard_request(chat_id, period, target_date_str, loading_msg_id, is_edit=False, reply_to_id=incoming_message_id)

        return jsonify({"status": "ok"})
    
    # HTML Landing Page
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Toggl Bot Status</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            background-color: #1a1a1a; /* Dark gray/black */
            color: #e0e0e0;
            font-family: 'Courier New', Courier, monospace; /* Monospace for that retro/code feel */
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            overflow: hidden;
            position: relative;
        }

        /* Cozy Minecraft-like Background Gradient */
        .background {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(to bottom, #0f0c29, #302b63, #24243e);
            z-index: -1;
        }
        
        /* Pixel stars/particles */
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
            background: rgba(0, 0, 0, 0.5);
            padding: 40px;
            border: 4px solid #4a4a4a; /* Pixel border look */
            border-radius: 4px; /* Slight rounding but mostly square */
            box-shadow: 0 0 20px rgba(0,0,0,0.8);
        }

        h1 {
            font-size: 3rem;
            margin-bottom: 10px;
            text-shadow: 4px 4px 0px #000;
            color: #50c878; /* Emerald green */
        }

        p {
            font-size: 1.2rem;
            margin-bottom: 30px;
            color: #ccc;
        }

        .buttons {
            display: flex;
            gap: 20px;
            justify-content: center;
        }

        .btn {
            text-decoration: none;
            color: #fff;
            padding: 15px 30px;
            font-weight: bold;
            border: 2px solid #fff;
            background: rgba(255, 255, 255, 0.1);
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
            position: relative;
            overflow: hidden;
        }

        .btn:hover {
            background: #fff;
            color: #1a1a1a;
            box-shadow: 0 0 15px rgba(255, 255, 255, 0.5);
            transform: translateY(-3px);
        }

        .btn-github:hover {
            background: #6cc644; /* GitHub Greenish */
            border-color: #6cc644;
        }

        .btn-docs:hover {
            background: #4078c0; /* Blueish */
            border-color: #4078c0;
        }

        /* Minecraft Torch flicker effect overlay */
        .torch-light {
            position: absolute;
            width: 100%;
            height: 100%;
            background: radial-gradient(circle at 50% 50%, rgba(255, 160, 0, 0.05), transparent 60%);
            pointer-events: none;
            animation: flicker 3s infinite alternate;
        }

        @keyframes flicker {
            0% { opacity: 0.8; transform: scale(1); }
            100% { opacity: 1; transform: scale(1.02); }
        }

    </style>
</head>
<body>
    <div class="background">
        <!-- Generated stars via JS below -->
    </div>
    <div class="torch-light"></div>

    <div class="container">
        <h1>🟢 Bot is Active</h1>
        <p>The Toggl Status Checker is running smoothly.</p>
        
        <div class="buttons">
            <a href="https://github.com/TirthNotFoundthedev/Toggl-Manager-Webhook" target="_blank" class="btn btn-github">GitHub</a>
            <a href="#" class="btn btn-docs">Documentation</a>
        </div>
    </div>

    <script>
        // Create random stars
        const bg = document.querySelector('.background');
        for(let i=0; i<50; i++) {
            let star = document.createElement('div');
            star.className = 'star';
            star.style.left = Math.random() * 100 + '%';
            star.style.top = Math.random() * 100 + '%';
            star.style.animationDelay = Math.random() * 5 + 's';
            bg.appendChild(star);
        }
    </script>
</body>
</html>
    """
    return render_template_string(html_content)

# ... (handle_status_request and handle_today_request stay here) ...

def handle_leaderboard_request(chat_id, period, target_date_str, message_id, is_edit=False, reply_to_id=None):
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
        report = get_leaderboard_report(users, period=period, target_date_str=target_date_str, timezone_str='Asia/Kolkata')
        
        # Trigger Sync for all users (in background-ish, one by one)
        # Only if not a fully cached report (though leaderboard is mix, we sync always to be sure)
        for user in users:
             api = user.get('toggl_token')
             if api:
                 sync_user_data(supabase, user.get('id'), api)

        # Generate Navigation Keyboard
        keyboard = get_leaderboard_keyboard(period, target_date_str)
        
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

def handle_settings_request(chat_id, sender_id, incoming_message_id):
    """Entry point for /settings."""
    try:
        response = supabase.table('Users').select("*").eq('tele_id', str(sender_id)).execute()
        user = response.data[0] if response.data else None
        
        if not user:
            # User not found, show registration
            text = "👋 *It looks like you're not registered!* \n\nRegister now to link your Toggl account and appear on the leaderboard."
            keyboard = {
                "inline_keyboard": [[{"text": "Register (New Profile) ✨", "callback_data": "reg:new"}]]
            }
            send_message(chat_id, text, reply_to_message_id=incoming_message_id, reply_markup=keyboard)
        else:
            name = user.get('user_name', 'Unknown').capitalize()
            text = f"⚙️ *Settings for {name}*\n\nYour current Toggl token is configured.\nWhat would you like to update?"
            keyboard = {
                "inline_keyboard": [
                    [{"text": "Change Name ✏️", "callback_data": "settings:name"}],
                    [{"text": "Change Toggl Token 🔑", "callback_data": "settings:token"}]
                ]
            }
            send_message(chat_id, text, reply_to_message_id=incoming_message_id, reply_markup=keyboard)
            
    except Exception as e:
        print(f"Settings Request Error: {e}")
        send_message(chat_id, "Error accessing settings.")

def handle_name_update(chat_id, sender_id, new_name, reply_to_id):
    """Updates the user name in the database or creates a new profile."""
    if len(new_name) > 15:
        send_message(chat_id, "❌ Name too long. Max 15 characters.", reply_to_message_id=reply_to_id)
        return

    try:
        # 1. Try to find user by tele_id
        res_tele = supabase.table('Users').select("*").eq('tele_id', str(sender_id)).execute()
        user_by_tele = res_tele.data[0] if res_tele.data else None
        
        if user_by_tele:
            # User exists with this Telegram ID - just update their name
            supabase.table('Users').update({'user_name': new_name}).eq('tele_id', str(sender_id)).execute()
            send_message(chat_id, f"✅ Display name updated to *{new_name}*.", reply_to_message_id=reply_to_id)
            return

        # 2. If not found by tele_id, check if a user with this name already exists (migration/manual entry case)
        res_name = supabase.table('Users').select("*").ilike('user_name', new_name).execute()
        user_by_name = res_name.data[0] if res_name.data else None
        
        if user_by_name:
            # User exists by name but has no tele_id (or a different one)
            # Link this Telegram ID to the existing profile
            supabase.table('Users').update({'tele_id': str(sender_id)}).eq('id', user_by_name['id']).execute()
            send_message(chat_id, f"✅ Welcome back, *{new_name}*! Your Telegram account has been linked to your profile.", reply_to_message_id=reply_to_id)
        else:
            # 3. Truly new user - Create entry
            supabase.table('Users').insert({'tele_id': str(sender_id), 'user_name': new_name}).execute()
            send_message(chat_id, f"✅ Profile created with name *{new_name}*.\n\n*Next Step:* Please provide your Toggl API Token to link your account.", 
                         reply_markup={"force_reply": True})

    except Exception as e:
        print(f"Name Update Error: {e}")
        send_message(chat_id, "❌ Failed to update name.", reply_to_message_id=reply_to_id)

def handle_token_update(chat_id, sender_id, new_token, reply_to_id):
    """Updates the Toggl token in the database."""
    try:
        # Check if user exists
        res = supabase.table('Users').select("*").eq('tele_id', str(sender_id)).execute()
        user = res.data[0] if res.data else None
        
        if not user:
             send_message(chat_id, "❌ Profile not found. Please set your display name first using /settings.", reply_to_message_id=reply_to_id)
             return
             
        # Optional: Validate token with Toggl?
        # For now, just save it.
        supabase.table('Users').update({'toggl_token': new_token}).eq('tele_id', str(sender_id)).execute()
        send_message(chat_id, "✅ Toggl API Token updated successfully! You're all set.", reply_to_message_id=reply_to_id)

    except Exception as e:
        print(f"Token Update Error: {e}")
        send_message(chat_id, "❌ Failed to update token.", reply_to_message_id=reply_to_id)

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
                        # Sync in background
                        sync_user_data(supabase, user.get('id'), toggl_token)
        else:
             # Find specific
            found = False
            for user in users:
                if user.get('user_name', '').lower() == target_name:
                    found = True
                    user_id_db = user.get('id')
                    user_name = user.get('user_name', 'Unknown')
                    toggl_token = user.get('toggl_token')
                    if toggl_token:
                        status_str = get_user_status_string(user_name.capitalize(), toggl_token)
                        status_messages.append(status_str)
                        # Sync in background
                        sync_user_data(supabase, user_id_db, toggl_token)
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

def handle_today_request(chat_id, target_name, detailed, sender_id, message_id, is_edit=False, target_date_str=None):
    try:
        if is_edit:
            edit_message(chat_id, message_id, "⏳ Updating...")
            
        response = supabase.table('Users').select("*").execute()
        users = response.data
        
        target_name = target_name.lower()
        target_user = None
        
        if target_name == "all":
            # Handle "All" for today
            reports = []
            for user in users:
                api = user.get('toggl_token')
                name = user.get('user_name', 'User').capitalize()
                cached = user.get('user_data')
                if api:
                    rep = get_daily_report(name, api, timezone_str='Asia/Kolkata', detailed=detailed, target_date_str=target_date_str, cached_entries=cached)
                    reports.append(rep)
                    
                    # Sync if not a cached result
                    if "Cached Data" not in rep:
                        sync_user_data(supabase, user.get('id'), api)
            
            final_report = ("\n" + "-"*10 + "\n").join(reports)
            if not reports:
                final_report = "No users to report."
            
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
                cached = target_user.get('user_data')
                if not api_token:
                    final_report = f"⚠️ {user_name} has no Toggl token."
                    keyboard = None
                else:
                    final_report = get_daily_report(user_name, api_token, timezone_str='Asia/Kolkata', detailed=detailed, target_date_str=target_date_str, cached_entries=cached)
                    
                    # Sync after success (if not using cache)
                    if "Cached Data" not in final_report:
                        sync_user_data(supabase, target_user.get('id'), api_token)

                    # Add Toggle Button
                    current_view = "detailed" if detailed else "normal"
                    keyboard = get_report_keyboard(user_name, current_view, target_date_str)

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
