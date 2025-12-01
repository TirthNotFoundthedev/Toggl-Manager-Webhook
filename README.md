# Toggl Status Checker Webhook Bot

A Google Cloud Function (Python) Telegram bot that interacts with Toggl Track and Supabase to provide real-time status updates and daily time tracking reports for a team.

## Features

*   **Webhook-based**: Runs efficiently on serverless infrastructure (Google Cloud Run Functions).
*   **Supabase Integration**: Manages user data (Telegram IDs, Toggl tokens, Names) securely.
*   **Toggl Track API**: Fetches real-time status and time entry history.
*   **Commands**:
    *   `/hi`: Simple health check/greeting.
    *   `/users`: Lists all configured users in the system.
    *   `/status [all|username]`: Checks if users are currently tracking time.
        *   Default (`all`): Checks everyone except the sender.
        *   Specific user: Checks status for that user.
    *   `/today [username] [detailed]`: Generates a daily report for the current day (Asia/Kolkata timezone).
        *   **Grouped View**: Aggregates time by description/project.
        *   **Detailed View**: Lists every individual time entry with start/stop times.
        *   **Self/Others**: Can check your own stats or others'.
*   **Interactive Feedback**: Uses "Processing..." messages and edits them with results to provide immediate feedback.
*   **Formatted Output**: Uses Markdown for clean, readable reports with calculated totals.

## Setup

1.  **Prerequisites**:
    *   Google Cloud Account (for Cloud Run/Functions).
    *   Telegram Bot Token (via BotFather).
    *   Supabase Project (with a `Users` table: `user_name`, `toggl_token`, `tele_id`).
    *   Toggl Track Account (for API tokens).

2.  **Environment Variables**:
    Set these in your `.env` file (for local dev) or Google Cloud Console:
    ```
    TELEGRAM_BOT_TOKEN=your_bot_token
    SUPABASE_URL=your_supabase_url
    SUPABASE_KEY=your_supabase_anon_key
    ```

3.  **Local Development**:
    ```bash
    # Install dependencies
    pip install -r requirements.txt

    # Run with functions-framework
    functions-framework --target=telegram_webhook --debug --port=5000
    ```

4.  **Deployment (Continuous Deployment)**:
    *   Connect this repository to Google Cloud Run Functions.
    *   Set the **Build source** to this repo.
    *   Set the **Entry point** to `telegram_webhook`.
    *   Pushing to the `main` branch will trigger a new deployment.

## Project Structure

*   `main.py`: Entry point for the Cloud Function. Handles Telegram webhook updates and command routing.
*   `toggl_api/`: Package containing Toggl API logic.
    *   `client.py`: Functions for fetching time entries, status, and generating reports.
*   `requirements.txt`: Python dependencies.
*   `Procfile`: Configuration for Google Cloud Run to start the `functions-framework`.
