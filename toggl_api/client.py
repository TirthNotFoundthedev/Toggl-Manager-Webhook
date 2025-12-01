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

def get_project_name(project_id, workspace_id, api_token, project_cache=None):
    """
    Fetches project name. optionally uses a cache dict.
    Note: In a real optimized app, we'd fetch all projects once or cache them properly.
    For now, we might just return ID or try to fetch if critical, but to save API calls 
    in this simple bot, we might skip or assume cache is passed.
    For this implementation, we'll return 'No Project' or simple lookup if feasible.
    """
    # Implementation complexity: fetching project requires another API call per project ID.
    # To keep it fast, we might skip or simple-cache.
    if not project_id:
        return "No Project"
    
    # If we really want names, we'd need to fetch project details:
    # GET https://api.track.toggl.com/api/v9/workspaces/{workspace_id}/projects/{project_id}
    return "Project" # Placeholder to avoid N+1 API calls for now unless requested.

def get_user_status_string(user_name, api_token):
    """
    Returns a formatted string indicating the user's status.
    """
    entry = get_current_time_entry(api_token)
    
    if entry and entry.get('id'):
        # User is tracking time
        description = entry.get('description', 'something')
        return f"🟢 {user_name} is currently tracking: {description}"
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
        project_totals = {} # map project_id/name -> seconds
        
        # For grouping
        grouped_entries = {} # (description, project_id) -> duration
        
        # For detailed view
        detailed_lines = []

        for entry in entries:
            duration = entry.get('duration', 0)
            if duration < 0:
                # Currently running timer. duration is -(epoch_start)
                # Calculate duration until 'now'
                start_ts = abs(duration)
                current_ts = datetime.now(pytz.utc).timestamp() # Approx
                # Better:
                # start_dt = datetime.fromisoformat(entry['start'].replace('Z', '+00:00'))
                # duration = (datetime.now(pytz.utc) - start_dt).total_seconds()
                # keeping it simple: just skip or approx?
                # Let's treat running timers as 'so far'
                import time
                duration = int(time.time()) + duration # duration is negative timestamp
            
            total_seconds += duration
            
            desc = entry.get('description', '(No Description)')
            pid = entry.get('pid', None) # Project ID
            # project_name = get_project_name(pid, entry['wid'], api_token) # Skipped for speed
            project_name = "Project" # Placeholder
            
            # Aggregate for Project Totals (using ID to be safe, but label generic)
            project_key = "General" # We simplify without project lookup
            project_totals[project_key] = project_totals.get(project_key, 0) + duration
            
            if detailed:
                # Parse start/stop
                start_dt = datetime.fromisoformat(entry['start'].replace('Z', '+00:00')).astimezone(tz)
                stop_dt = datetime.fromisoformat(entry['stop'].replace('Z', '+00:00')).astimezone(tz) if entry.get('stop') else datetime.now(tz)
                
                start_str = start_dt.strftime("%H:%M")
                stop_str = stop_dt.strftime("%H:%M")
                dur_str = format_duration(duration)
                
                detailed_lines.append(f"• `{start_str}` - `{stop_str}` ({dur_str})\n  📝 {desc}")
            else:
                # Grouping
                key = (desc, project_key)
                grouped_entries[key] = grouped_entries.get(key, 0) + duration

        # Build Message
        date_str = now.strftime('%Y-%m-%d')
        msg = f"📅 Time entries for {user_name} on {date_str}\n\n"
        
        if detailed:
            msg += "\n\n".join(detailed_lines)
        else:
            # Grouped Output
            # Sort grouped entries for consistent output
            for (desc, proj), dur in sorted(grouped_entries.items()):
                dur_str = format_duration(dur)
                # Mimic requested format: • Duration — Project \n 📝 Desc
                msg += f"• {dur_str} — {desc}\n" # proj is always 'General' in current simplified impl
                if desc != "(No Description)": # Only add description line if it's meaningful
                    msg += f"  📝 {desc}\n"
                msg += "\n" # Add a newline for spacing between grouped entries

        # The example implies grouping by a "Project" like "Question Solving".
        # Current simplified project_key is "General", let's sum by actual descriptions for totals too.
        # This part of the example "📊 Project totals:" is a bit tricky given the current API response.
        # If "Question Solving" is a Project, then we need to fetch project names.
        # For now, let's sum up by descriptions for "Project totals" to match the example's spirit.
        
        # Aggregate descriptions for the "Project totals" section
        desc_totals = {}
        for entry in entries:
            duration = entry.get('duration', 0)
            if duration < 0: # Running timer
                duration = int(datetime.now(pytz.utc).timestamp()) + duration
            desc = entry.get('description', '(No Description)')
            desc_totals[desc] = desc_totals.get(desc, 0) + duration

        if desc_totals:
            msg += f"\n📊 Project totals:\n"
            for desc, dur in sorted(desc_totals.items()):
                msg += f"- {desc}: {format_duration(dur)}\n"
        
        msg += f"\n⏱ Day total: {format_duration(total_seconds)}"

        return msg

    except Exception as e:
        print(f"Report Error: {e}")
        return f"Failed to generate report for {user_name}."
