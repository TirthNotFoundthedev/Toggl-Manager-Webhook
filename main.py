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
        "usage": "/status [user]"
    },
    "today": {
        "description": "Get a daily report of time tracked.",
        "usage": "/today [user] [detailed]"
    },
    "leaderboard": {
        "description": "View the leaderboard for time tracked.",
        "usage": "/leaderboard [daily/weekly] [offset]"
    },
    "users": {
        "description": "List all configured users.",
        "usage": "/users"
    },
    "wake": {
        "description": "Nudge a user to start working if they aren't tracking time.",
        "usage": "/wake [user] [message]"
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
                        # Ask for custom message via ForceReply
                        # Format: 🔔 Wake <Target>: ...
                        prompt = f"🔔 Wake *{target}*: Enter custom message (or . for none):"
                        force_reply = {"force_reply": True, "input_field_placeholder": "Wake up!"}
                        send_message(chat_id, prompt, reply_markup=force_reply)

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
        if data and "message" in data:
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
                    
                    # Check if it's a Custom Message prompt from the bot
                    reply_text = reply_to.get("text", "")
                    if reply_text.startswith("🔔 Wake") and ":" in reply_text:
                        try:
                            # Extract Target from "🔔 Wake Target: ..."
                            parts_prompt = reply_text.split(":")
                            if len(parts_prompt) > 1:
                                prefix_part = parts_prompt[0] # "🔔 Wake Tirth"
                                # Remove the known prefix "🔔 Wake " safely
                                target_name = prefix_part.replace("🔔 Wake ", "", 1).strip()
                                
                                custom_message = text
                                if custom_message == ".":
                                    custom_message = ""
                                    
                                loading_msg = send_message(chat_id, f"🔔 Nudging {target_name}...", reply_to_message_id=incoming_message_id)
                                loading_msg_id = loading_msg.get("result", {}).get("message_id") if loading_msg else None
                                
                                result = perform_wake(supabase, sender_id, sender_name, target_name, custom_message, incoming_message_id)
                                
                                if loading_msg_id:
                                    delete_message(chat_id, loading_msg_id)
                                send_message(chat_id, result, reply_to_message_id=incoming_message_id)
                                return jsonify({"status": "ok"})
                        except Exception as e:
                            print(f"Error parsing wake prompt: {e}")

                    # Try to handle as wake reply
                    if handle_wake_reply(supabase, reply_msg_id, text, sender_name):
                        return jsonify({"status": "ok"}) # Handled, exit
                
                parts = text.split()
                command = parts[0].lower()
                
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
