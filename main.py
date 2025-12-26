import os
import logging
from typing import Dict, List
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)
from database import MongoDB

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ALLOWED_GROUP_ID = os.getenv('ALLOWED_GROUP_ID')  # Your group ID
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID')  # Your user ID
MONGODB_URI = os.getenv('MONGODB_URI')

# Initialize MongoDB
db = MongoDB(MONGODB_URI)

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Check if user is in allowed group
def is_allowed_group(chat_id: str) -> bool:
    return str(chat_id) == ALLOWED_GROUP_ID

# Check if user is admin
def is_admin(user_id: str) -> bool:
    return str(user_id) == ADMIN_USER_ID

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_group(update.effective_chat.id):
        return
    
    user = update.effective_user
    welcome_message = (
        f"🎯 Welcome {user.first_name} to Study Target Bot!\n\n"
        "I help you track your study targets and progress.\n\n"
        "📚 Available Commands:\n"
        "/settarget - Set a new study target\n"
        "/mytargets - View your current targets\n"
        "/progress - Update target progress\n"
        "/completed - Mark target as completed\n"
        "/stats - View your study statistics\n"
        "/help - Show help message\n"
    )
    
    await update.message.reply_text(welcome_message)

# Set target command
async def set_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_group(update.effective_chat.id):
        return
    
    if not context.args:
        await update.message.reply_text(
            "Please specify your target.\n"
            "Example: /settarget Complete Python course chapter 5"
        )
        return
    
    user_id = update.effective_user.id
    target_text = " ".join(context.args)
    
    # Create target data
    target_data = {
        "user_id": user_id,
        "username": update.effective_user.username or update.effective_user.first_name,
        "target": target_text,
        "status": "active",
        "progress": 0,
        "created_at": datetime.now(),
        "deadline": None,
        "completed_at": None
    }
    
    # Save to database
    target_id = db.add_target(target_data)
    
    # Ask for deadline
    keyboard = [
        [
            InlineKeyboardButton("1 day", callback_data=f"deadline_{target_id}_1"),
            InlineKeyboardButton("3 days", callback_data=f"deadline_{target_id}_3"),
            InlineKeyboardButton("7 days", callback_data=f"deadline_{target_id}_7"),
        ],
        [InlineKeyboardButton("No deadline", callback_data=f"deadline_{target_id}_0")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Target set successfully!\n\n"
        f"📝 Target: {target_text}\n"
        f"🆔 Target ID: {target_id}\n\n"
        "Would you like to set a deadline?",
        reply_markup=reply_markup
    )

# Deadline callback handler
async def deadline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    target_id = data[1]
    days = int(data[2])
    
    if days > 0:
        deadline = datetime.now() + timedelta(days=days)
        db.update_target_deadline(target_id, deadline)
        await query.edit_message_text(
            text=f"⏰ Deadline set for {days} day(s) from now!"
        )
    else:
        await query.edit_message_text(
            text="✅ Target saved without deadline."
        )

# View my targets
async def my_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_group(update.effective_chat.id):
        return
    
    user_id = update.effective_user.id
    targets = db.get_user_targets(user_id)
    
    if not targets:
        await update.message.reply_text("You don't have any active targets.")
        return
    
    message = "📚 Your Current Targets:\n\n"
    for i, target in enumerate(targets, 1):
        status_icon = "✅" if target["status"] == "completed" else "⏳"
        progress_bar = "█" * (target["progress"] // 20) + "░" * (5 - target["progress"] // 20)
        
        message += (
            f"{i}. {status_icon} {target['target']}\n"
            f"   📊 Progress: {progress_bar} {target['progress']}%\n"
            f"   🆔 ID: {target['_id']}\n"
        )
        
        if target.get('deadline'):
            deadline = target['deadline'].strftime("%Y-%m-%d")
            message += f"   ⏰ Deadline: {deadline}\n"
        
        message += "\n"
    
    await update.message.reply_text(message)

# Update progress
async def update_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_group(update.effective_chat.id):
        return
    
    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: /progress <target_id> <percentage>\n"
            "Example: /progress abc123 50"
        )
        return
    
    target_id, progress = context.args[0], context.args[1]
    
    try:
        progress = int(progress)
        if not 0 <= progress <= 100:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a valid percentage (0-100).")
        return
    
    success = db.update_target_progress(target_id, progress)
    
    if success:
        await update.message.reply_text(
            f"📊 Progress updated to {progress}%!\n"
            f"Target ID: {target_id}"
        )
    else:
        await update.message.reply_text("Target not found or update failed.")

# Mark as completed
async def mark_completed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_group(update.effective_chat.id):
        return
    
    if not context.args:
        await update.message.reply_text(
            "Please specify target ID.\n"
            "Example: /completed abc123"
        )
        return
    
    target_id = context.args[0]
    success = db.complete_target(target_id)
    
    if success:
        await update.message.reply_text(
            f"🎉 Target marked as completed!\n"
            f"Target ID: {target_id}"
        )
    else:
        await update.message.reply_text("Target not found.")

# View statistics
async def view_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_group(update.effective_chat.id):
        return
    
    user_id = update.effective_user.id
    stats = db.get_user_stats(user_id)
    
    message = (
        f"📊 Study Statistics for @{update.effective_user.username or update.effective_user.first_name}\n\n"
        f"🎯 Total Targets: {stats['total_targets']}\n"
        f"✅ Completed: {stats['completed_targets']}\n"
        f"⏳ Active: {stats['active_targets']}\n"
        f"📈 Completion Rate: {stats['completion_rate']}%\n"
        f"🔥 Current Streak: {stats['current_streak']} days\n"
        f"🏆 Best Streak: {stats['best_streak']} days"
    )
    
    await update.message.reply_text(message)

# Admin: Export all data
async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_group(update.effective_chat.id):
        return
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return
    
    # Export data to CSV or JSON
    data = db.export_all_data()
    
    # In a real implementation, you would create a file and send it
    await update.message.reply_text(
        "📊 Data export initiated.\n"
        f"Total records: {len(data)}\n\n"
        "Note: In production, this would generate and send a file."
    )

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_group(update.effective_chat.id):
        return
    
    help_text = (
        "📚 Study Bot Help\n\n"
        "Commands:\n"
        "/start - Start the bot\n"
        "/settarget <description> - Set a new study target\n"
        "/mytargets - View your current targets\n"
        "/progress <id> <percentage> - Update target progress\n"
        "/completed <id> - Mark target as completed\n"
        "/stats - View your study statistics\n"
        "/export - Admin: Export all data (admin only)\n"
        "/help - Show this help message\n\n"
        "Tips:\n"
        "• Set realistic targets\n"
        "• Update progress regularly\n"
        "• Celebrate completed targets!\n"
        "• Use /stats to track your progress"
    )
    
    await update.message.reply_text(help_text)

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_chat:
        await update.effective_chat.send_message(
            "An error occurred. Please try again later."
        )

# Main function
def main():
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("settarget", set_target))
    application.add_handler(CommandHandler("mytargets", my_targets))
    application.add_handler(CommandHandler("progress", update_progress))
    application.add_handler(CommandHandler("completed", mark_completed))
    application.add_handler(CommandHandler("stats", view_stats))
    application.add_handler(CommandHandler("export", export_data))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(deadline_callback, pattern="^deadline_"))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()