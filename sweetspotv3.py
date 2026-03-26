import requests
import json
import datetime
import time
import sys
import logging
import os
import shutil
import threading
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlencode
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes
)
import asyncio

# ============================================
# CONFIGURATION - EDIT THESE VALUES
# ============================================

# Your Telegram Bot Token (get from @BotFather)
TELEGRAM_BOT_TOKEN = "8074227016:AAF7g_KVy1Km3d6Dxnxhy3CFkrWzTh81VN0"  # Replace with your actual token

# Email configuration (optional - for email notifications)
EMAIL_CONFIG = {
    "email_sender": "",  # Your email
    "email_password": "",  # Your app password
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "default_recipient": ""  # Default recipient
}

# ============================================
# END OF CONFIGURATION
# ============================================

# Conversation states
(COURSE_UUID, SEARCH_DATE, START_TIME, END_TIME, NUM_PLAYERS, 
 CHECK_INTERVAL, SEARCH_NAME, EMAIL_RECIPIENT) = range(8)

class SweetspotTelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://platform.sweetspot.io"
        self.active_searches = {}
        self.email_config_file = "email_config.json"
        self.searches_folder = "searches"
        self.user_sessions = {}  # Store user session data
        
        # Setup directories
        self.setup_directories()
        
        # Load or create email configuration
        self.email_config = self.setup_email_config()
        
        # Setup logging
        self.setup_logging()
        
        # Load all saved searches
        self.load_all_searches()
        
        # Create application
        self.application = Application.builder().token(token).build()
        self.setup_handlers()
    
    def setup_directories(self):
        """Create necessary directories"""
        directories = ["logs", "responses", "found_times", self.searches_folder, "active_searches"]
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
    
    def setup_logging(self):
        """Setup logging"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"logs/telegram_bot_{timestamp}.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        self.logger = logging.getLogger(__name__)
    
    def setup_email_config(self) -> Dict:
        """Setup email configuration"""
        config_file = "email_config.json"
        
        # If email_config.json exists, load it
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"Error loading email config: {e}")
        
        # Otherwise use the EMAIL_CONFIG from above
        config = EMAIL_CONFIG.copy()
        
        # Save it for future use
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self.logger.info("Email configuration saved")
        except Exception as e:
            self.logger.error(f"Error saving email config: {e}")
        
        return config
    
    def load_all_searches(self):
        """Load all saved searches from disk"""
        self.saved_searches = {}
        if os.path.exists(self.searches_folder):
            for filename in os.listdir(self.searches_folder):
                if filename.endswith('.json'):
                    search_id = filename[:-5]
                    try:
                        with open(os.path.join(self.searches_folder, filename), 'r', encoding='utf-8') as f:
                            self.saved_searches[search_id] = json.load(f)
                    except Exception as e:
                        self.logger.error(f"Error loading search {filename}: {e}")
    
    def save_search(self, search_id: str, config: Dict):
        """Save a search configuration"""
        filename = os.path.join(self.searches_folder, f"{search_id}.json")
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        self.saved_searches[search_id] = config
        self.logger.info(f"Search saved: {search_id}")
    
    def delete_search(self, search_id: str):
        """Delete a saved search"""
        if search_id in self.saved_searches:
            filename = os.path.join(self.searches_folder, f"{search_id}.json")
            if os.path.exists(filename):
                os.remove(filename)
                del self.saved_searches[search_id]
                return True
        return False
    
    def setup_handlers(self):
        """Setup telegram command handlers"""
        # Basic commands
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("commands", self.commands_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("searches", self.list_searches))
        self.application.add_handler(CommandHandler("active", self.active_searches_command))
        self.application.add_handler(CommandHandler("stop", self.stop_search_command))
        self.application.add_handler(CommandHandler("stopall", self.stop_all_searches_command))
        self.application.add_handler(CommandHandler("email", self.email_config_command))
        
        # Conversation handler for creating new search
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('new', self.new_search_start)],
            states={
                COURSE_UUID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_course_uuid)],
                SEARCH_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_search_date)],
                START_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_start_time)],
                END_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_end_time)],
                NUM_PLAYERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_num_players)],
                CHECK_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_check_interval)],
                SEARCH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_search_name)],
                EMAIL_RECIPIENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_email_recipient)],
            },
            fallbacks=[CommandHandler('cancel', self.cancel_conversation)],
        )
        self.application.add_handler(conv_handler)
        
        # Callback query handler for inline buttons
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        # Store user's chat ID for notifications
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        if 'chat_ids' not in context.bot_data:
            context.bot_data['chat_ids'] = {}
        
        context.bot_data['chat_ids'][user_id] = chat_id
        
        welcome_message = """
🎯 *Sweetspot Booking Bot* 🎯

Welcome! I help you monitor and book tee times on Sweetspot.

*Commands:*
/commands - Show all available commands
/new - Create a new tee time search
/searches - View your saved searches
/active - View currently active searches
/stop [name] - Stop a specific search
/stopall - Stop all active searches
/status - Check bot status
/email - Configure email notifications
/help - Show this help message

Get started with /new to create your first search!
"""
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        await self.start_command(update, context)
    
    async def commands_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all available commands"""
        commands_message = """
📋 *All Available Commands*

*Search Management:*
/new - Create a new tee time search
/searches - List all saved searches
/active - Show currently running searches
/stop [name] - Stop a specific search
/stopall - Stop all active searches

*Information:*
/status - Check bot status and stats
/email - View email configuration
/commands - Show this command list
/help - Show welcome message
/start - Start the bot

*Tips:*
• Use /new to create a search
• Searches run until the tee time passes
• You'll get Telegram notifications when times are found
• Use /active to monitor running searches
• Stop searches with /stop [search_name]
"""
        await update.message.reply_text(commands_message, parse_mode='Markdown')
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check bot status"""
        status_message = f"""
📊 *Bot Status*

*Active searches:* {len(self.active_searches)}
*Saved searches:* {len(self.saved_searches)}
*Email configured:* {'✅' if self.email_config['email_sender'] else '❌'}

*Active searches details:*
"""
        if self.active_searches:
            for search_id, bot in self.active_searches.items():
                status_message += f"\n🔍 *{search_id}*"
                status_message += f"\n  • Searches: {bot.search_count}"
                status_message += f"\n  • Found: {bot.found_count}"
                status_message += f"\n  • Runs until: {bot.end_time.strftime('%Y-%m-%d %H:%M')}"
                status_message += f"\n  • Duration: {bot.get_search_duration()}\n"
        else:
            status_message += "\nNo active searches"
        
        await update.message.reply_text(status_message, parse_mode='Markdown')
    
    async def list_searches(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all saved searches"""
        if not self.saved_searches:
            await update.message.reply_text("📁 No saved searches found. Use /new to create one!")
            return
        
        message = "📁 *Your Saved Searches:*\n\n"
        
        for search_id, config in self.saved_searches.items():
            criteria = config["search_criteria"]
            status = "🟢 ACTIVE" if search_id in self.active_searches else "⚪ INACTIVE"
            message += f"*{search_id}* - {status}\n"
            message += f"📅 {criteria['date']} {criteria['start_time']}-{criteria['end_time']}\n"
            message += f"👥 {criteria['num_players']} players\n\n"
        
        # Create inline keyboard for actions
        keyboard = []
        for search_id in self.saved_searches.keys():
            keyboard.append([
                InlineKeyboardButton(f"▶️ Run {search_id}", callback_data=f"run_{search_id}"),
                InlineKeyboardButton(f"❌ Delete {search_id}", callback_data=f"delete_{search_id}")
            ])
        
        # Split keyboard into chunks of 2 to avoid too many buttons
        chunked_keyboard = [keyboard[i:i+2] for i in range(0, len(keyboard), 2)]
        
        reply_markup = InlineKeyboardMarkup(chunked_keyboard)
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def active_searches_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show active searches"""
        if not self.active_searches:
            await update.message.reply_text("🔄 No active searches running.\n\nUse /new to create a search or /searches to run a saved one.")
            return
        
        message = "🔄 *Active Searches:*\n\n"
        
        for search_id, bot in self.active_searches.items():
            message += f"*{search_id}*\n"
            message += f"⏱️ Running for: {bot.get_search_duration()}\n"
            message += f"🔍 Checks performed: {bot.search_count}\n"
            message += f"🎯 Times found: {bot.found_count}\n"
            message += f"⏰ Runs until: {bot.end_time.strftime('%Y-%m-%d %H:%M')}\n"
            
            if bot.found_count > 0:
                message += f"✅ Last found: {bot.last_found_time.strftime('%H:%M:%S') if bot.last_found_time else 'N/A'}\n"
            message += "\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def stop_search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stop a specific search"""
        if not context.args:
            await update.message.reply_text(
                "Usage: /stop [search_name]\n\n"
                "Example: /stop SaturdayMorning\n\n"
                "Use /active to see running searches."
            )
            return
        
        search_name = context.args[0]
        if search_name in self.active_searches:
            self.stop_search(search_name)
            await update.message.reply_text(f"✅ Search '{search_name}' stopped successfully!")
        else:
            await update.message.reply_text(f"❌ No active search found with name '{search_name}'\n\nUse /active to see running searches.")
    
    async def stop_all_searches_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stop all active searches"""
        if not self.active_searches:
            await update.message.reply_text("No active searches to stop.")
            return
        
        count = len(self.active_searches)
        
        # Create confirmation keyboard
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, stop all", callback_data="confirm_stopall"),
                InlineKeyboardButton("❌ No, cancel", callback_data="cancel_stopall")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"⚠️ Are you sure you want to stop all {count} active searches?",
            reply_markup=reply_markup
        )
    
    async def email_config_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show email configuration status"""
        if not self.email_config['email_sender']:
            message = "📧 *Email not configured*\n\nTo enable email notifications, edit the email_config.json file with your email settings."
        else:
            message = f"""
📧 *Email Configuration*

*Sender:* {self.email_config['email_sender']}
*Default recipient:* {self.email_config['default_recipient']}
*SMTP Server:* {self.email_config['smtp_server']}:{self.email_config['smtp_port']}

To update email settings, edit the email_config.json file.
"""
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def new_search_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start conversation to create new search"""
        user_id = update.effective_user.id
        context.user_data['search_config'] = {}
        
        await update.message.reply_text(
            "🔍 *Create New Search*\n\n"
            "Let's create a new tee time search! Follow the prompts.\n\n"
            "First, please enter the Golf Course UUID:",
            parse_mode='Markdown'
        )
        return COURSE_UUID
    
    async def get_course_uuid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get course UUID"""
        context.user_data['search_config']['course_uuid'] = update.message.text.strip()
        await update.message.reply_text(
            "✅ Got it!\n\n"
            "Now enter the date (YYYY-MM-DD):\n"
            "Example: 2024-12-25"
        )
        return SEARCH_DATE
    
    async def get_search_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get search date"""
        date_str = update.message.text.strip()
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            context.user_data['search_config']['date'] = date_str
            await update.message.reply_text(
                "✅ Date saved!\n\n"
                "Enter start time (HH:MM):\n"
                "Example: 08:00"
            )
            return START_TIME
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid date format. Please use YYYY-MM-DD format.\n"
                "Example: 2024-12-25"
            )
            return SEARCH_DATE
    
    async def get_start_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get start time"""
        time_str = update.message.text.strip()
        try:
            datetime.strptime(time_str, '%H:%M')
            context.user_data['search_config']['start_time'] = time_str
            await update.message.reply_text(
                "✅ Start time saved!\n\n"
                "Enter end time (HH:MM):\n"
                "Example: 18:00"
            )
            return END_TIME
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid time format. Please use HH:MM format.\n"
                "Example: 08:00"
            )
            return START_TIME
    
    async def get_end_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get end time"""
        time_str = update.message.text.strip()
        try:
            datetime.strptime(time_str, '%H:%M')
            context.user_data['search_config']['end_time'] = time_str
            await update.message.reply_text(
                "✅ End time saved!\n\n"
                "Enter number of players (1-4):"
            )
            return NUM_PLAYERS
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid time format. Please use HH:MM format.\n"
                "Example: 18:00"
            )
            return END_TIME
    
    async def get_num_players(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get number of players"""
        try:
            players = int(update.message.text.strip())
            if 1 <= players <= 4:
                context.user_data['search_config']['num_players'] = players
                await update.message.reply_text(
                    f"✅ {players} players selected!\n\n"
                    "Enter check interval in minutes (how often to search):\n"
                    "Example: 5"
                )
                return CHECK_INTERVAL
            else:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Please enter a number between 1 and 4."
            )
            return NUM_PLAYERS
    
    async def get_check_interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get check interval"""
        try:
            interval = int(update.message.text.strip())
            if interval > 0:
                context.user_data['search_config']['check_interval'] = interval
                await update.message.reply_text(
                    "✅ Check interval saved!\n\n"
                    "Give this search a name (no spaces):\n"
                    "Example: SaturdayMorning"
                )
                return SEARCH_NAME
            else:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Please enter a positive number."
            )
            return CHECK_INTERVAL
    
    async def get_search_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get search name"""
        search_name = update.message.text.strip().replace(' ', '_')
        
        if search_name in self.saved_searches:
            await update.message.reply_text(
                f"❌ A search with name '{search_name}' already exists.\n"
                "Please choose another name:"
            )
            return SEARCH_NAME
        
        context.user_data['search_config']['name'] = search_name
        
        # Ask about email notifications
        if self.email_config['email_sender']:
            await update.message.reply_text(
                f"📧 Optional: Enter email for notifications (or 'skip' to disable):\n"
                f"Default: {self.email_config['default_recipient']}"
            )
            return EMAIL_RECIPIENT
        else:
            # No email configured, skip
            return await self.finish_search_creation(update, context)
    
    async def get_email_recipient(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get email recipient"""
        email = update.message.text.strip()
        
        if email.lower() == 'skip':
            context.user_data['search_config']['email_recipient'] = None
        else:
            context.user_data['search_config']['email_recipient'] = email
        
        return await self.finish_search_creation(update, context)
    
    async def finish_search_creation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Finish creating search and save it"""
        config = context.user_data['search_config']
        search_name = config.pop('name')
        
        # Calculate end time (when search should stop)
        search_date = datetime.strptime(config['date'], '%Y-%m-%d')
        end_time = datetime.strptime(config['end_time'], '%H:%M').time()
        search_end_datetime = datetime.combine(search_date.date(), end_time)
        
        # Build full config
        full_config = {
            "course_uuid": config['course_uuid'],
            "search_criteria": {
                "date": config['date'],
                "start_time": config['start_time'],
                "end_time": config['end_time'],
                "num_players": config['num_players'],
                "preferred_times": [],
                "max_price": None,
            },
            "monitoring": {
                "check_interval_minutes": config['check_interval'],
                "search_end_datetime": search_end_datetime.isoformat(),
                "notify_on_found": True,
                "stop_on_first_found": True
            },
            "notification": {
                "email_enabled": config.get('email_recipient') is not None,
                "email_recipient": config.get('email_recipient', self.email_config['default_recipient'])
            },
            "advanced": {
                "save_all_responses": False,
                "beep_on_found": False,
                "retry_on_error": True,
                "max_retries": 3
            }
        }
        
        # Save search
        self.save_search(search_name, full_config)
        
        # Ask if user wants to run it now
        keyboard = [
            [
                InlineKeyboardButton("✅ Run now", callback_data=f"run_{search_name}"),
                InlineKeyboardButton("📋 Save only", callback_data="save_only")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Calculate how long the search will run
        run_duration = search_end_datetime - datetime.now()
        days = run_duration.days
        hours = run_duration.seconds // 3600
        
        duration_text = ""
        if days > 0:
            duration_text += f"{days} days "
        if hours > 0:
            duration_text += f"{hours} hours"
        if days == 0 and hours == 0:
            duration_text = "less than an hour"
        
        await update.message.reply_text(
            f"✅ *Search '{search_name}' created successfully!*\n\n"
            f"*Configuration:*\n"
            f"📅 Date: {config['date']}\n"
            f"⏰ Time: {config['start_time']} - {config['end_time']}\n"
            f"👥 Players: {config['num_players']}\n"
            f"🔄 Check every: {config['check_interval']} minutes\n"
            f"⏱️ Will run until: {search_end_datetime.strftime('%Y-%m-%d %H:%M')}\n"
            f"⏳ Duration: {duration_text}\n\n"
            f"*What now?*\n"
            f"• Run now to start searching immediately\n"
            f"• Save only to run it later from /searches\n"
            f"• Use /active to monitor running searches\n"
            f"• Use /commands to see all available commands",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        return ConversationHandler.END
    
    async def cancel_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel conversation"""
        await update.message.reply_text(
            "❌ Search creation cancelled.\n\n"
            "Use /new to start over or /commands to see all commands."
        )
        return ConversationHandler.END
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "save_only":
            await query.edit_message_text(
                "✅ Search saved successfully!\n\n"
                "Use /searches to view and run your saved searches."
            )
        
        elif data == "confirm_stopall":
            count = len(self.active_searches)
            for search_id in list(self.active_searches.keys()):
                self.stop_search(search_id)
            await query.edit_message_text(f"✅ Stopped all {count} active searches.")
        
        elif data == "cancel_stopall":
            await query.edit_message_text("❌ Stop all cancelled.")
        
        elif data.startswith("run_"):
            search_name = data[4:]
            if search_name in self.saved_searches:
                # Store user's chat ID for notifications
                user_id = update.effective_user.id
                chat_id = update.effective_chat.id
                
                # Start the search
                success = self.start_search(
                    search_name, 
                    self.saved_searches[search_name],
                    user_id,
                    chat_id
                )
                if success:
                    await query.edit_message_text(
                        f"✅ *Search '{search_name}' started!*\n\n"
                        f"You will receive Telegram notifications here when tee times are found.\n\n"
                        f"Use /active to monitor this search.",
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text(
                        f"❌ Search '{search_name}' is already running!\n\n"
                        f"Use /active to see running searches."
                    )
        
        elif data.startswith("delete_"):
            search_name = data[7:]
            if self.delete_search(search_name):
                await query.edit_message_text(f"✅ Search '{search_name}' deleted successfully!")
            else:
                await query.edit_message_text(f"❌ Failed to delete '{search_name}'")
    
    def start_search(self, search_id: str, config: Dict, user_id: int = None, chat_id: int = None) -> bool:
        """Start a new search in background thread"""
        if search_id in self.active_searches:
            return False
        
        # Create and start bot
        bot = SweetspotSearchBot(
            search_id, 
            config, 
            self.email_config, 
            self,
            user_id,
            chat_id
        )
        
        # Start in separate thread
        thread = threading.Thread(target=bot.run_continuous_search, daemon=True)
        thread.start()
        
        # Store bot
        self.active_searches[search_id] = bot
        
        self.logger.info(f"Search started: {search_id}")
        return True
    
    def stop_search(self, search_id: str):
        """Stop an active search"""
        if search_id in self.active_searches:
            bot = self.active_searches[search_id]
            bot.stop_search()
            del self.active_searches[search_id]
            self.logger.info(f"Search stopped: {search_id}")
    
    async def send_telegram_notification(self, chat_id: int, search_id: str, tee_times: List[Dict]):
        """Send notification via Telegram"""
        if not tee_times or not chat_id:
            return
        
        message = f"🎯 *Tee Times Found!*\n\n"
        message += f"Search: *{search_id}*\n"
        message += f"Found {len(tee_times)} available times:\n\n"
        
        for i, tee_time in enumerate(tee_times[:5]):
            message += f"{i+1}. 🕐 {tee_time.get('local_time')} - {tee_time.get('available_slots')} spots\n"
        
        if len(tee_times) > 5:
            message += f"\n... and {len(tee_times) - 5} more times"
        
        message += f"\n\n🔗 Book here: https://golfstar.se/boka-starttid/\n\n"
        message += f"Use /active to check search status."
        
        try:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='Markdown'
            )
            self.logger.info(f"Telegram notification sent to chat {chat_id}")
        except Exception as e:
            self.logger.error(f"Failed to send Telegram notification: {e}")
    
    def run(self):
        """Run the bot"""
        self.logger.info("Starting Sweetspot Telegram Bot...")
        self.logger.info(f"Bot token: {self.token[:10]}... (hidden)")
        self.logger.info(f"Email configured: {'Yes' if self.email_config['email_sender'] else 'No'}")
        self.logger.info(f"Saved searches: {len(self.saved_searches)}")
        
        # Start the bot
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


class SweetspotSearchBot:
    """Individual search bot instance"""
    def __init__(self, search_id: str, config: Dict, email_config: Dict, 
                 telegram_bot: SweetspotTelegramBot, user_id: int = None, 
                 chat_id: int = None):
        self.search_id = search_id
        self.config = config
        self.email_config = email_config
        self.telegram_bot = telegram_bot
        self.user_id = user_id
        self.chat_id = chat_id
        self.should_stop = False
        self.last_found_time = None
        
        # Calculate end time from config
        end_time_str = config['monitoring'].get('search_end_datetime')
        if end_time_str:
            self.end_time = datetime.fromisoformat(end_time_str)
        else:
            # Fallback to end of search day
            search_date = datetime.strptime(config['search_criteria']['date'], '%Y-%m-%d')
            end_time = datetime.strptime(config['search_criteria']['end_time'], '%H:%M').time()
            self.end_time = datetime.combine(search_date.date(), end_time)
        
        # Setup session
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, */*',
            'Accept-Language': 'sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://golfstar.se/',
            'Origin': 'https://golfstar.se',
        })
        
        self.base_url = "https://platform.sweetspot.io"
        
        # Stats
        self.search_count = 0
        self.found_count = 0
        self.start_time = datetime.now()
        
        # Setup logging
        self.setup_bot_logging()
    
    def setup_bot_logging(self):
        """Setup logging for this bot"""
        log_file = f"logs/{self.search_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        self.logger = logging.getLogger(self.search_id)
        if not self.logger.handlers:
            handler = logging.FileHandler(log_file, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def stop_search(self):
        """Signal the bot to stop"""
        self.should_stop = True
    
    def is_search_active(self) -> bool:
        """Check if search should continue"""
        if self.should_stop:
            return False
        
        # Check if we've passed the end time
        now = datetime.now()
        if now > self.end_time:
            self.logger.info(f"Search ended: passed end time {self.end_time}")
            return False
        
        # Check if we found something and should stop
        if self.config['monitoring']['stop_on_first_found'] and self.found_count > 0:
            return False
        
        return True
    
    def get_search_duration(self) -> str:
        """Get formatted search duration"""
        duration = datetime.now() - self.start_time
        hours, remainder = divmod(duration.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if duration.days > 0:
            return f"{duration.days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    
    def search_tee_times(self) -> List[Dict]:
        """Search for tee times"""
        criteria = self.config['search_criteria']
        course_uuid = self.config['course_uuid']
        
        try:
            search_date = datetime.strptime(criteria['date'], '%Y-%m-%d')
        except ValueError:
            self.logger.error(f"Invalid date: {criteria['date']}")
            return []
        
        # Convert to UTC
        from_after_utc, from_before_utc = self.convert_to_utc_range(
            search_date, criteria['start_time'], criteria['end_time']
        )
        
        params = {
            'course.uuid': course_uuid,
            'from[after]': from_after_utc,
            'from[before]': from_before_utc,
            'limit': 9999,
            'order[from]': 'asc',
            'page': 1,
        }
        
        self.search_count += 1
        self.logger.info(f"Search #{self.search_count} at {datetime.now().strftime('%H:%M:%S')}")
        
        try:
            response = self.session.get(
                f"{self.base_url}/api/tee-times",
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                available_times = self.filter_tee_times(data, search_date, criteria)
                
                if available_times:
                    self.found_count += 1
                    self.last_found_time = datetime.now()
                    self.logger.info(f"Found {len(available_times)} tee times")
                    return available_times
                else:
                    self.logger.debug("No available times found")
                
        except Exception as e:
            self.logger.error(f"Search error: {e}")
        
        return []
    
    def convert_to_utc_range(self, date: datetime, start_time: str, end_time: str) -> Tuple[str, str]:
        """Convert local times to UTC"""
        start_dt = datetime.combine(date.date(), datetime.strptime(start_time, '%H:%M').time())
        end_dt = datetime.combine(date.date(), datetime.strptime(end_time, '%H:%M').time())
        
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        
        utc_offset = timedelta(hours=1)  # CET/CEST offset
        
        from_after_utc = (start_dt - utc_offset).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        from_before_utc = (end_dt - utc_offset).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        
        return from_after_utc, from_before_utc
    
    def filter_tee_times(self, data: Any, search_date: datetime, criteria: Dict) -> List[Dict]:
        """Filter tee times based on criteria"""
        tee_times = self.extract_tee_times(data)
        
        if not tee_times:
            return []
        
        filtered = []
        num_players = criteria['num_players']
        
        for tee_time in tee_times:
            try:
                utc_time_str = tee_time.get('from', '')
                if not utc_time_str:
                    continue
                
                # Convert to local time
                if 'Z' in utc_time_str:
                    utc_dt = datetime.fromisoformat(utc_time_str.replace('Z', '+00:00'))
                else:
                    utc_dt = datetime.fromisoformat(utc_time_str)
                
                local_dt = utc_dt + timedelta(hours=1)
                local_time = local_dt.time()
                local_date = local_dt.date()
                
                # Check date and time
                if local_date != search_date.date():
                    continue
                
                start_time = datetime.strptime(criteria['start_time'], '%H:%M').time()
                end_time = datetime.strptime(criteria['end_time'], '%H:%M').time()
                
                if not (start_time <= local_time <= end_time):
                    continue
                
                # Check availability
                available_slots = tee_time.get('available_slots', 0)
                if available_slots < num_players:
                    continue
                
                # Check if it's a preferred time (if any)
                preferred_times = criteria.get('preferred_times', [])
                if preferred_times:
                    local_time_str = local_dt.strftime('%H:%M')
                    if local_time_str not in preferred_times:
                        continue
                
                # Check price
                max_price = criteria.get('max_price')
                if max_price is not None:
                    price = tee_time.get('price')
                    if isinstance(price, dict):
                        price_amount = price.get('amount')
                        if price_amount and price_amount > max_price:
                            continue
                
                # Add to results
                tee_time_copy = tee_time.copy()
                tee_time_copy['local_time'] = local_dt.strftime('%H:%M')
                tee_time_copy['local_datetime'] = local_dt.isoformat()
                filtered.append(tee_time_copy)
                
            except Exception as e:
                self.logger.debug(f"Error processing tee time: {e}")
                continue
        
        return filtered
    
    def extract_tee_times(self, data: Any) -> List[Dict]:
        """Extract tee times from API response"""
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            if 'data' in data and isinstance(data['data'], list):
                return data['data']
        return []
    
    def notify_found(self, tee_times: List[Dict]):
        """Send notification when tee times are found"""
        if not tee_times:
            return
        
        self.logger.info(f"Found {len(tee_times)} tee times")
        
        # Email notification
        if self.config['notification']['email_enabled']:
            self.send_email_notification(tee_times)
        
        # Telegram notification
        if self.chat_id:
            # Run async function in thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                self.telegram_bot.send_telegram_notification(
                    self.chat_id, 
                    self.search_id, 
                    tee_times
                )
            )
            loop.close()
        
        # Save to file
        self.save_found_times(tee_times)
    
    def send_email_notification(self, tee_times: List[Dict]):
        """Send email notification"""
        try:
            recipient = self.config['notification']['email_recipient']
            
            msg = MIMEMultipart()
            msg['From'] = self.email_config['email_sender']
            msg['To'] = recipient
            msg['Subject'] = f"🎯 [{self.search_id}] Tee Times Found!"
            
            # Create email body
            criteria = self.config['search_criteria']
            body = f"""
Sweetspot Booking Bot - Tee Times Found!

Search: {self.search_id}
Date: {criteria['date']}
Time: {criteria['start_time']} - {criteria['end_time']}
Players: {criteria['num_players']}

Found {len(tee_times)} tee times at {datetime.now().strftime('%H:%M:%S')}

Best options:
"""
            for i, tee_time in enumerate(tee_times[:5]):
                body += f"{i+1}. {tee_time.get('local_time')} - {tee_time.get('available_slots')} slots\n"
            
            body += f"\nBook here: https://golfstar.se/boka-starttid/"
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Send email
            with smtplib.SMTP(self.email_config['smtp_server'], self.email_config['smtp_port']) as server:
                server.starttls()
                server.login(self.email_config['email_sender'], self.email_config['email_password'])
                server.send_message(msg)
            
            self.logger.info(f"Email sent to {recipient}")
            
        except Exception as e:
            self.logger.error(f"Email error: {e}")
    
    def save_found_times(self, tee_times: List[Dict]):
        """Save found tee times to file"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"found_times/{self.search_id}_{timestamp}.json"
            
            data = {
                'search_id': self.search_id,
                'found_at': datetime.now().isoformat(),
                'search_count': self.search_count,
                'tee_times': tee_times
            }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            
            self.logger.info(f"Saved found times to {filename}")
            
        except Exception as e:
            self.logger.error(f"Save error: {e}")
    
    def run_continuous_search(self):
        """Run continuous search until end time"""
        self.logger.info(f"Starting search: {self.search_id}")
        self.logger.info(f"Will run until: {self.end_time.strftime('%Y-%m-%d %H:%M')}")
        
        interval_minutes = self.config['monitoring']['check_interval_minutes']
        
        try:
            while self.is_search_active():
                # Search for tee times
                found_times = self.search_tee_times()
                
                if found_times:
                    # Notify
                    self.notify_found(found_times)
                    
                    if self.config['monitoring']['stop_on_first_found']:
                        self.logger.info("Stopping search (first found)")
                        break
                
                # Calculate time until next check
                next_check = datetime.now() + timedelta(minutes=interval_minutes)
                self.logger.debug(f"Next check at: {next_check.strftime('%H:%M:%S')}")
                
                # Wait for next check
                if self.is_search_active():
                    time.sleep(interval_minutes * 60)
            
            # Log completion reason
            if datetime.now() > self.end_time:
                self.logger.info(f"Search completed: reached end time {self.end_time}")
            elif self.found_count > 0 and self.config['monitoring']['stop_on_first_found']:
                self.logger.info(f"Search completed: found {self.found_count} times")
            else:
                self.logger.info(f"Search stopped: {self.search_count} searches performed")
            
        except Exception as e:
            self.logger.error(f"Search error: {e}")
        finally:
            # Remove from active searches when done
            if self.search_id in self.telegram_bot.active_searches:
                del self.telegram_bot.active_searches[self.search_id]
            
            # Send completion notification via Telegram
            if self.chat_id:
                completion_msg = f"✅ *Search '{self.search_id}' has completed*\n\n"
                completion_msg += f"🔍 Total searches: {self.search_count}\n"
                completion_msg += f"🎯 Times found: {self.found_count}\n\n"
                
                if self.found_count > 0:
                    completion_msg += "Check the chat history for found times!"
                else:
                    completion_msg += "No tee times were found during the search period."
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    self.telegram_bot.application.bot.send_message(
                        chat_id=self.chat_id,
                        text=completion_msg,
                        parse_mode='Markdown'
                    )
                )
                loop.close()


def main():
    """Main function"""
    print("\n" + "="*70)
    print("🎯 SWEETSPOT TELEGRAM BOT")
    print("="*70)
    print("Starting Telegram bot for Sweetspot booking...")
    print("="*70)
    
    # Check if token is configured
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n❌ ERROR: Bot token not configured!")
        print("\nPlease edit the script and set your Telegram Bot Token:")
        print("1. Go to @BotFather on Telegram")
        print("2. Create a new bot or get your existing bot token")
        return
    
    # Create and run bot
    bot = SweetspotTelegramBot(TELEGRAM_BOT_TOKEN)
    
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting tips:")
        print("1. Make sure your bot token is correct")
        print("2. Check your internet connection")
        print("3. Verify that python-telegram-bot is installed correctly")


if __name__ == "__main__":
    main()