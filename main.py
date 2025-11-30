import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    await update.message.reply_text("Hello! I am running on Google Cloud Run.")

def main() -> None:
    """Start the bot."""
    # Get the token from environment variable
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("TELEGRAM_TOKEN environment variable not set")
        return

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(token).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))

    # Run the bot using webhook
    # Cloud Run passes the port to listen on as an environment variable PORT
    port = int(os.environ.get("PORT", 8080))
    webhook_url = os.environ.get("WEBHOOK_URL")
    
    if not webhook_url:
         logger.error("WEBHOOK_URL environment variable not set")
         return

    logger.info(f"Starting webhook on port {port}, url: {webhook_url}")
    
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token,
        webhook_url=f"{webhook_url}/{token}",
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
