import os
import logging
from typing import Dict, List
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes,
    ConversationHandler
)
from database import MongoDB

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ALLOWED_GROUP_ID = os.getenv('ALLOWED_GROUP_ID')  # Your group ID
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID')  # Your user ID
MONGODB_URI = os.getenv('MONGODB_URI')

# Conversation states
RULES, ACCEPT = range(2)

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

# Mute user in group
async def mute_user(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Mute a user in the group"""
    try:
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False
        )
        
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=datetime.now() + timedelta(days=365)  # Mute for 1 year or until registered
        )
        return True
    except Exception as e:
        logger.error(f"Failed to mute user {user_id}: {e}")
        return False

# Unmute user in group
async def unmute_user(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Unmute a user in the group"""
    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False
        )
        
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions
        )
        return True
    except Exception as e:
        logger.error(f"Failed to unmute user {user_id}: {e}")
        return False

# Handler for new members joining the group
async def new_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new members joining the group"""
    if not is_allowed_group(update.effective_chat.id):
        return
    
    # Check if it's a group chat
    if update.effective_chat.type not in ['group', 'supergroup']:
        return
    
    # Get new members
    for member in update.message.new_chat_members:
        user_id = member.id
        username = member.username or member.first_name
        
        # Skip if it's the bot itself
        if member.id == context.bot.id:
            continue
        
        # Check if user is already registered
        if db.is_user_registered(user_id, update.effective_chat.id):
            await update.message.reply_text(
                f"Welcome back, {username}! You're already registered."
            )
            continue
        
        # Mute the new member
        await mute_user(update.effective_chat.id, user_id, context)
        
        # Add to registration database
        registration_id = db.add_registration(user_id, update.effective_chat.id, username)
        
        # Create registration button
        keyboard = [[
            InlineKeyboardButton(
                "📝 Register Now", 
                url=f"https://t.me/{context.bot.username}?start=register_{registration_id}"
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send welcome message with registration button
        welcome_message = (
            f"👋 Welcome {username} to our study group!\n\n"
            "📋 **Group Rules:**\n"
            "1. Be respectful to all members\n"
            "2. No spam or self-promotion\n"
            "3. Stay on topic - this is a study group\n"
            "4. Use appropriate language\n"
            "5. Follow Telegram's Terms of Service\n\n"
            "⚠️ **You are currently muted**\n"
            "To participate in the group, you must complete registration.\n"
            "Click the button below to start registration."
        )
        
        await update.message.reply_text(
            welcome_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

# Start command - modified to handle registration
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    # Check if it's a registration start
    if context.args and context.args[0].startswith('register_'):
        registration_id = context.args[0].replace('register_', '')
        
        # Show rules
        rules_message = (
            "📋 **Group Rules Declaration**\n\n"
            "Please read and accept the following rules:\n\n"
            "1. **Respect All Members**: Be polite and respectful to everyone.\n"
            "2. **No Spam**: Do not post irrelevant content or advertisements.\n"
            "3. **Study Focus**: Keep discussions related to learning and studies.\n"
            "4. **No Harassment**: Any form of harassment will result in immediate ban.\n"
            "5. **Follow Guidelines**: Adhere to group-specific guidelines.\n"
            "6. **Help Others**: Share knowledge and help fellow students.\n"
            "7. **Report Issues**: Report any problems to admins.\n\n"
            "By accepting, you agree to follow these rules."
        )
        
        keyboard = [[
            InlineKeyboardButton("✅ I Accept All Rules", callback_data=f"accept_rules_{registration_id}")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            rules_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    # Regular start command
    if update.effective_chat.type == 'private':
        welcome_message = (
            f"👋 Hello {user.first_name}!\n\n"
            "I'm the Study Bot. I help manage study targets and group registrations.\n\n"
            "If you were asked to register for a group, please use the registration link provided in the group.\n\n"
            "Commands available in group:\n"
            "/settarget - Set a new study target\n"
            "/mytargets - View your current targets\n"
            "/progress - Update target progress\n"
            "/completed - Mark target as completed\n"
            "/stats - View your study statistics\n"
            "/help - Show help message"
        )
        await update.message.reply_text(welcome_message)
    elif is_allowed_group(update.effective_chat.id):
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

# Accept rules callback handler
async def accept_rules_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle rules acceptance"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    if len(data) != 3:
        await query.edit_message_text("Registration error. Please contact admin.")
        return
    
    registration_id = data[2]
    user_id = query.from_user.id
    
    # In a real implementation, you would verify the registration_id
    # For now, we'll accept it
    
    # Mark rules as accepted in database
    success = db.accept_rules(user_id, int(ALLOWED_GROUP_ID))
    
    if success:
        # Unmute user in group
        await unmute_user(int(ALLOWED_GROUP_ID), user_id, context)
        
        # Send confirmation message in private chat
        await query.edit_message_text(
            "✅ **Registration Successful!**\n\n"
            "You have been unmuted in the group.\n"
            "You can now participate in discussions.\n\n"
            "Welcome to our study community! 🎓",
            parse_mode='Markdown'
        )
        
        # Send welcome message in group
        try:
            await context.bot.send_message(
                chat_id=int(ALLOWED_GROUP_ID),
                text=f"🎉 Welcome @{query.from_user.username or query.from_user.first_name} to our study group!\n"
                     "Your registration is complete. Happy studying! 📚"
            )
        except Exception as e:
            logger.error(f"Failed to send group message: {e}")
    else:
        await query.edit_message_text(
            "❌ Registration failed. Please contact an admin for assistance."
        )

# Modified command handlers to check registration status
async def check_registration_and_execute(update: Update, context: ContextTypes.DEFAULT_TYPE, command_func):
    """Check if user is registered before executing command"""
    if not is_allowed_group(update.effective_chat.id):
        return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Check if user is registered
    if not db.is_user_registered(user_id, chat_id):
        await update.message.reply_text(
            "⚠️ You need to complete registration to use this command.\n"
            "Please wait for the registration prompt or contact an admin."
        )
        return
    
    # Execute the command
    await command_func(update, context)

# Wrapper functions for commands
async def set_target_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_registration_and_execute(update, context, set_target)

async def my_targets_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_registration_and_execute(update, context, my_targets)

async def update_progress_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_registration_and_execute(update, context, update_progress)

async def mark_completed_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_registration_and_execute(update, context, mark_completed)

async def view_stats_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_registration_and_execute(update, context, view_stats)

async def export_data_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_registration_and_execute(update, context, export_data)

async def help_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_registration_and_execute(update, context, help_command)

# Original command functions (unchanged from your code)
async def set_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Please specify your target.\n"
            "Example: /settarget Complete Python course chapter 5"
        )
        return
    
    user_id = update.effective_user.id
    target_text = " ".join(context.args)
    
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
    
    target_id = db.add_target(target_data)
    
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

async def my_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def update_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def mark_completed(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def view_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return
    
    data = db.export_all_data()
    
    await update.message.reply_text(
        "📊 Data export initiated.\n"
        f"Total records: {len(data)}\n\n"
        "Note: In production, this would generate and send a file."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# Admin command to manually register users
async def register_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to manually register a user"""
    if not is_allowed_group(update.effective_chat.id):
        return
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: /registeruser <user_id> or reply to user's message with /registeruser"
        )
        return
    
    # Check if replying to a message
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        username = update.message.reply_to_message.from_user.username
    else:
        try:
            user_id = int(context.args[0])
            username = context.args[1] if len(context.args) > 1 else "Unknown"
        except ValueError:
            await update.message.reply_text("Invalid user ID.")
            return
    
    # Register user
    success = db.accept_rules(user_id, update.effective_chat.id)
    
    if success:
        # Unmute user
        await unmute_user(update.effective_chat.id, user_id, context)
        await update.message.reply_text(
            f"✅ User {username} (ID: {user_id}) has been registered and unmuted."
        )
    else:
        await update.message.reply_text("Failed to register user.")

# Main function
def main():
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS, 
        new_member_handler
    ))
    application.add_handler(CommandHandler("settarget", set_target_wrapper))
    application.add_handler(CommandHandler("mytargets", my_targets_wrapper))
    application.add_handler(CommandHandler("progress", update_progress_wrapper))
    application.add_handler(CommandHandler("completed", mark_completed_wrapper))
    application.add_handler(CommandHandler("stats", view_stats_wrapper))
    application.add_handler(CommandHandler("export", export_data_wrapper))
    application.add_handler(CommandHandler("help", help_command_wrapper))
    application.add_handler(CommandHandler("registeruser", register_user))
    application.add_handler(CallbackQueryHandler(deadline_callback, pattern="^deadline_"))
    application.add_handler(CallbackQueryHandler(accept_rules_callback, pattern="^accept_rules_"))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()