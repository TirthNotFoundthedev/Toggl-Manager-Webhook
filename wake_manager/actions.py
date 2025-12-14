import os
import json
from datetime import datetime, timedelta
import pytz
import requests
from dotenv import load_dotenv
from html import escape

# Load envs for standalone usage if needed
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Cooldown duration: 1 hour
COOLDOWN_DURATION = timedelta(hours=1)

def send_telegram_message(chat_id, text, reply_to_message_id=None):
    """Internal helper to send message without circular dependency."""
    if not BOT_TOKEN:
        return None
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
        
    try:
        return requests.post(url, json=payload).json()
    except Exception as e:
        print(f"Wake Manager Send Error: {e}")
        return None

def get_current_toggl_entry(api_token):
    """Checks if user is currently tracking time (simple check)."""
    try:
        response = requests.get(
            "https://api.track.toggl.com/api/v9/me/time_entries/current",
            auth=(api_token, "api_token"),
            timeout=5
        )
        if response.status_code == 200:
            return response.json()
        return None
    except Exception:
        return None

def is_cooldown_active(user_row, sender_id):
    """Checks if sender is on cooldown for this target."""
    wake_cooldown = user_row.get('wake_cooldown')
    
    # Parse JSON if string
    if isinstance(wake_cooldown, str):
        try:
            wake_cooldown = json.loads(wake_cooldown)
        except json.JSONDecodeError:
            wake_cooldown = {}
    elif not isinstance(wake_cooldown, dict):
        wake_cooldown = {}
        
    sender_str = str(sender_id)
    if sender_str in wake_cooldown:
        expiry_str = wake_cooldown[sender_str]
        try:
            expiry = datetime.fromisoformat(expiry_str)
            # Ensure expiry is timezone aware (UTC) if not already
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=pytz.utc)
                
            now = datetime.now(pytz.utc)
            return False

        except ValueError:
            return False
    return False

def set_cooldown(supabase, user_row, sender_id):
    """Updates the cooldown for the sender on this target."""
    if not supabase: return
    
    user_id = user_row['id']
    wake_cooldown = user_row.get('wake_cooldown')
    
    # Parse/Init
    if isinstance(wake_cooldown, str):
        try:
            wake_cooldown = json.loads(wake_cooldown)
        except:
            wake_cooldown = {}
    elif not isinstance(wake_cooldown, dict):
        wake_cooldown = {}
        
    # Set new expiry
    new_expiry = datetime.now(pytz.utc) + COOLDOWN_DURATION
    wake_cooldown[str(sender_id)] = new_expiry.isoformat()
    
    try:
        # User requested raw JSON object structure, so we pass the dict directly.
        supabase.table('Users').update({'wake_cooldown': wake_cooldown}).eq('id', user_id).execute()
    except Exception as e:
        print(f"Failed to update cooldown: {e}")

def log_wake_event(supabase, sender_id, receiver_id, message_id, command_msg_id):
    """Logs the wake event to Supabase."""
    if not supabase: return
    try:
        supabase.table('WakeLogs').insert({
            'sender_id': str(sender_id),
            'receiver_id': str(receiver_id),
            'message_id': message_id,
            'command_msg_id': command_msg_id,
            'reply_used': False
        }).execute()
    except Exception as e:
        print(f"Failed to log wake event: {e}")

def perform_wake(supabase, sender_id, sender_name, target_name, custom_message, command_msg_id, users_cache=None):
    """
    Core logic to wake a single user.
    Returns a status string.
    """
    if not users_cache:
        # Fetch if not provided
        if not supabase: return "System Error: DB not connected."
        users_cache = supabase.table('Users').select("*").execute().data
        
    # Find Target
    target = next((u for u in users_cache if u.get('user_name', '').lower() == target_name.lower()), None)
    
    if not target:
        return f"User '{target_name}' not found."
        
    # 1. Check Self (Disabled for testing as requested)
    # if str(target.get('tele_id')) == str(sender_id):
    #     return "You cannot wake yourself."
        
    # 2. Check Cooldown
    if is_cooldown_active(target, sender_id):
        return f"Wait 1h before waking {target_name.capitalize()} again."
        
    # 3. Check Status (Don't wake if studying)
    if target.get('toggl_token'):
        entry = get_current_toggl_entry(target.get('toggl_token'))
        if entry:
            return f"{target_name.capitalize()} is already studying!"
            
    # 4. Send Message
    target_chat_id = target.get('tele_id')
    if not target_chat_id:
        return f"{target_name.capitalize()} has no Telegram ID."
        
    safe_sender = escape(sender_name)
    msg_text = f"⏰ <b>WAKE UP!</b>\n\n{safe_sender} is nudging you to start studying!"
    if custom_message:
        safe_custom = escape(custom_message)
        msg_text += f"\n\n💬 Message:\n<blockquote>{safe_custom}</blockquote>"
        
    resp = send_telegram_message(target_chat_id, msg_text)
    
    if resp and resp.get('ok'):
        msg_id = resp.get('result', {}).get('message_id')
        # Update DB
        set_cooldown(supabase, target, sender_id)
        # Log with command_msg_id
        log_wake_event(supabase, sender_id, target_chat_id, msg_id, command_msg_id)
        return f"Successfully woke {target_name.capitalize()}! 🔔"
    else:
        return f"Failed to send message to {target_name.capitalize()}."

def perform_wake_all(supabase, sender_id, sender_name, custom_message, command_msg_id):
    """Wakes all users except sender."""
    if not supabase: return "System Error."
    
    users = supabase.table('Users').select("*").execute().data
    results = []
    
    for user in users:
        name = user.get('user_name')
        # Disabled self-skip for testing as requested
        # if str(user.get('tele_id')) == str(sender_id):
        #     continue
            
        res = perform_wake(supabase, sender_id, sender_name, name, custom_message, command_msg_id, users_cache=users)
        
        # Format result for bulk list
        status_icon = "✅" if "Successfully" in res else "⚠️"
        if "already studying" in res: status_icon = "🔨"
        if "Wait 1h" in res: status_icon = "⏳"
        
        # Simplified result string
        short_res = res.replace(f"User '{name}' not found.", "Error").replace("You cannot wake yourself.", "Skip")
        results.append(f"{name.capitalize()}: {short_res}")
        
    return "📢 **Wake All Report**\n\n" + "\n".join(results)

def handle_wake_reply(supabase, reply_message_id, reply_text, replier_name):
    """
    Handles replies to wake messages.
    Finds the original wake event and forwards the reply to the sender.
    """
    if not supabase: return False
    
    try:
        # 1. Find valid wake log
        res = supabase.table('WakeLogs').select("*").eq('message_id', reply_message_id).execute()
        if not res.data:
            return False
            
        log = res.data[0]
        
        # 2. Check if already used
        if log.get('reply_used', False):
            return False # Already forwarded
            
        # 3. Get details
        original_sender_id = log['sender_id']
        command_msg_id = log['command_msg_id']
        
        # 4. Send Reply to Original Sender
        # Format: <name> : <reply>
        safe_replier = escape(replier_name)
        safe_reply = escape(reply_text)
        final_text = f"{safe_replier} : {safe_reply}"
        
        send_telegram_message(original_sender_id, final_text, reply_to_message_id=command_msg_id)
        
        # 5. Mark as used
        supabase.table('WakeLogs').update({'reply_used': True}).eq('id', log['id']).execute()
        return True
        
    except Exception as e:
        print(f"Wake Reply Error: {e}")
        return False
