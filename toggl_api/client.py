import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta
import pytz

def get_current_time_entry(api_token):
    """
    Fetches the current time entry for a given Toggl API token.
    Returns the time entry object if tracking, None otherwise.
    """
    try:
        response = requests.get(
            "https://api.track.toggl.com/api/v9/me/time_entries/current",
            auth=HTTPBasicAuth(api_token, "api_token"),
            timeout=5
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Toggl API Error: {e}")
        return None

def get_time_entries(api_token, start_date, end_date):
    """
    Fetches time entries between start_date and end_date (ISO strings).
    """
    try:
        params = {
            "start_date": start_date,
            "end_date": end_date
        }
        response = requests.get(
            "https://api.track.toggl.com/api/v9/me/time_entries",
            auth=HTTPBasicAuth(api_token, "api_token"),
            params=params,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Toggl API Error (History): {e}")
        return []

def format_duration(seconds):
    """Formats seconds into H:MM:SS"""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"`{int(h)}:{int(m):02d}:{int(s):02d}`"

def get_project_details(project_id, workspace_id, api_token):
    """
    Fetches project details to get the name.
    """
    if not project_id:
        return "No Project"
        
    url = f"https://api.track.toggl.com/api/v9/workspaces/{workspace_id}/projects/{project_id}"
    try:
        response = requests.get(
            url, 
            auth=HTTPBasicAuth(api_token, "api_token"),
            timeout=5
        )
        if response.status_code == 200:
            return response.json().get("name", "Unknown Project")
        return "Unknown Project"
    except Exception as e:
        print(f"Project Fetch Error: {e}")
        return "Unknown Project"

def get_user_status_string(user_name, api_token):
    """
    Returns a formatted string indicating the user's status.
    """
    entry = get_current_time_entry(api_token)
    
    if entry and entry.get('id'):
        # User is tracking time
        description = entry.get('description', '(No Description)')
        
        # Fetch project name for status
        pid = entry.get('pid')
        wid = entry.get('wid')
        project_name = ""
        if pid:
             name = get_project_details(pid, wid, api_token)
             project_name = f"[{name}] "
             
        return f"🟢 {user_name} is currently tracking: {project_name}{description}"
    else:
        # User is not tracking time
        return f"🔴 {user_name} is currently NOT tracking time."

def get_daily_report(user_name, api_token, timezone_str='UTC', detailed=False):
    """
    Generates a report for 'today' in the specified timezone.
    """
    try:
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Toggl expects UTC or proper offsets. formatting as ISO with TZ info.
        start_iso = start_of_day.isoformat()
        end_iso = end_of_day.isoformat()
        
        entries = get_time_entries(api_token, start_iso, end_iso)
        
        if not entries:
            return f"📅 No time entries found for {user_name} on {now.strftime('%Y-%m-%d')}."

        total_seconds = 0
        
        # Pre-fetch project names to minimize API calls
        # Identify unique PIDs
        unique_pids = set()
        pid_workspace_map = {} # pid -> wid
        for entry in entries:
            pid = entry.get('pid')
            if pid:
                unique_pids.add(pid)
                pid_workspace_map[pid] = entry.get('wid')
        
        # Fetch names
        project_names = {} # pid -> name
        for pid in unique_pids:
            project_names[pid] = get_project_details(pid, pid_workspace_map[pid], api_token)
            
        project_totals = {} # map Project Name -> seconds
        grouped_entries = {} # (description, project_name) -> duration
        
        detailed_lines = []

        for entry in entries:
            duration = entry.get('duration', 0)
            if duration < 0:
                # Currently running timer
                import time
                duration = int(time.time()) + duration 
            
            total_seconds += duration
            
            desc = entry.get('description', '(No Description)')
            pid = entry.get('pid')
            
            project_name = project_names.get(pid, "No Project") if pid else "No Project"
            
            # Aggregate for Project Totals
            project_totals[project_name] = project_totals.get(project_name, 0) + duration
            
            if detailed:
                # Parse start/stop
                start_dt = datetime.fromisoformat(entry['start'].replace('Z', '+00:00')).astimezone(tz)
                stop_dt = datetime.fromisoformat(entry['stop'].replace('Z', '+00:00')).astimezone(tz) if entry.get('stop') else datetime.now(tz)
                
                start_str = start_dt.strftime("%H:%M")
                stop_str = stop_dt.strftime("%H:%M")
                dur_str = format_duration(duration)
                
                # Include project name in detailed view too
                # Changed placement: Description first, then Project
                detailed_lines.append(f"• `{start_str}` - `{stop_str}` ({dur_str})\n  📝 {desc}")
                if project_name and project_name != "No Project":
                    detailed_lines.append(f"  📂 {project_name}")
            else:
                # Grouping by Description AND Project
                key = (desc, project_name)
                grouped_entries[key] = grouped_entries.get(key, 0) + duration

        # Build Message
        date_str = now.strftime('%Y-%m-%d')
        msg = f"📅 Time entries for {user_name} on {date_str}\n\n"
        
        if detailed:
            # Join with double newlines for spacing
            msg += "\n\n".join(detailed_lines)
        else:
            # Grouped Output
            # Sort grouped entries for consistent output
            for (desc, proj), dur in sorted(grouped_entries.items()):
                dur_str = format_duration(dur)
                # Changed placement: Description first, then Project
                msg += f"• {dur_str} — {desc}\n"
                if proj and proj != "No Project": # Only show project if it's available and not generic
                    msg += f"  📂 {proj}\n"
                msg += "\n" # Add a newline for spacing between grouped entries

        # Project Totals Section
        if project_totals:
            msg += f"📊 Project totals:\n"
            for proj, dur in sorted(project_totals.items()):
                msg += f"- {proj}: {format_duration(dur)}\n"
        
        msg += f"\n⏱ Day total: {format_duration(total_seconds)}"

        return msg

    except Exception as e:
        print(f"Report Error: {e}")
        return f"Failed to generate report for {user_name}."
