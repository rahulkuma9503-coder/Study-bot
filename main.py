import os
import logging
import threading
import time
from typing import Dict, List
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)
from database import MongoDB
from flask import Flask, jsonify
import uuid  # Add this import

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ALLOWED_GROUP_ID = os.getenv('ALLOWED_GROUP_ID')
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID')
MONGODB_URI = os.getenv('MONGODB_URI')
PORT = int(os.getenv('PORT', 10000))

# Create Flask app for health checks
app = Flask(__name__)

@app.route('/')
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

# Initialize MongoDB
db = MongoDB(MONGODB_URI)

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot status tracking
bot_status = {
    "is_running": False,
    "last_heartbeat": None,
    "start_time": None,
    "processed_messages": 0
}

# Check if user is in allowed group
def is_allowed_group(chat_id: str) -> bool:
    return str(chat_id) == ALLOWED_GROUP_ID

# Check if user is admin
def is_admin(user_id: str) -> bool:
    return str(user_id) == ADMIN_USER_ID

# Mute user in group
async def mute_user(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE, reason: str = "Not registered"):
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
            until_date=datetime.now() + timedelta(days=365)
        )
        logger.info(f"Muted user {user_id} in group {chat_id}: {reason}")
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
            can_invite_users=True,
            can_pin_messages=False
        )
        
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions
        )
        logger.info(f"Unmuted user {user_id} in group {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to unmute user {user_id}: {e}")
        return False

# Send registration prompt
async def send_registration_prompt(chat_id: int, user_id: int, username: str, context: ContextTypes.DEFAULT_TYPE, registration_id: str = None):
    """Send registration prompt to user"""
    try:
        if not registration_id:
            # Create new registration
            registration_id = db.add_registration(user_id, chat_id, username)
        
        keyboard = [[
            InlineKeyboardButton(
                "📝 Register Now", 
                url=f"https://t.me/{context.bot.username}?start=register_{registration_id}"
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_message = (
            f"👋 @{username}, welcome to our study group!\n\n"
            "📋 **Group Rules:**\n"
            "1. Be respectful to all members\n"
            "2. No spam or self-promotion\n"
            "3. Stay on topic - this is a study group\n"
            "4. Use appropriate language\n"
            "5. Follow Telegram's Terms of Service\n\n"
            "⚠️ **You need to complete registration to participate**\n"
            "Click the button below to start registration."
        )
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=welcome_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send registration prompt to {user_id}: {e}")
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
        
        # Track member in database
        db.add_group_member(user_id, update.effective_chat.id, username)
        
        # Check if user is already registered
        if db.is_user_registered(user_id, update.effective_chat.id):
            await update.message.reply_text(
                f"Welcome back, @{username}! You're already registered."
            )
            continue
        
        # Mute the new member
        await mute_user(update.effective_chat.id, user_id, context, "New member registration required")
        
        # Send registration prompt
        await send_registration_prompt(
            update.effective_chat.id, 
            user_id, 
            username, 
            context
        )

# Command to check and register existing members
async def check_existing_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check existing members and register those who aren't"""
    if not is_allowed_group(update.effective_chat.id):
        return
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return
    
    await update.message.reply_text("🔍 Checking existing members...")
    
    # Get unregistered members
    unregistered_members = db.check_and_register_existing_members(
        update.effective_chat.id, 
        context
    )
    
    if not unregistered_members:
        await update.message.reply_text("✅ All members are already registered!")
        return
    
    # Process each unregistered member
    processed = 0
    for member in unregistered_members:
        try:
            # Try to get member info
            chat_member = await context.bot.get_chat_member(
                update.effective_chat.id,
                member["user_id"]
            )
            
            username = chat_member.user.username or chat_member.user.first_name
            
            # Mute the member
            await mute_user(
                update.effective_chat.id, 
                member["user_id"], 
                context, 
                "Existing member registration required"
            )
            
            # Send registration prompt
            await send_registration_prompt(
                update.effective_chat.id,
                member["user_id"],
                username,
                context,
                member["registration_id"]
            )
            
            processed += 1
            time.sleep(0.5)  # Avoid rate limiting
            
        except Exception as e:
            logger.error(f"Error processing member {member['user_id']}: {e}")
            continue
    
    await update.message.reply_text(
        f"✅ Processed {processed} unregistered members.\n"
        f"They have been muted and sent registration prompts."
    )

# Start command
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

# Modified wrapper to check registration for commands
async def check_registration_and_execute(update: Update, context: ContextTypes.DEFAULT_TYPE, command_func):
    """Check if user is registered before executing command"""
    if not is_allowed_group(update.effective_chat.id):
        return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Check if user is registered
    if not db.is_user_registered(user_id, chat_id):
        # Get registration status
        registration = db.get_registration_status(user_id, chat_id)
        
        # If not in registration database, add them
        if not registration:
            username = update.effective_user.username or update.effective_user.first_name
            registration_id = db.add_registration(user_id, chat_id, username)
        else:
            registration_id = str(registration.get('_id', ''))
        
        # Mute the user if they try to use commands
        await mute_user(chat_id, user_id, context, "Tried to use commands without registration")
        
        # Send registration prompt
        keyboard = [[
            InlineKeyboardButton(
                "📝 Register Now", 
                url=f"https://t.me/{context.bot.username}?start=register_{registration_id}"
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"⚠️ @{update.effective_user.username or update.effective_user.first_name}, "
            "you need to register before using bot commands.\n\n"
            "Click the button below to register:",
            reply_markup=reply_markup
        )
        return
    
    # Execute the command
    await command_func(update, context)

# Store temporary callback data for deadline buttons
deadline_callbacks = {}

# Set target command - FIXED VERSION
async def set_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set a new study target - Fixed to handle multiple targets"""
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
    try:
        target_id = db.add_target(target_data)
        
        if not target_id:
            await update.message.reply_text("❌ Failed to save target. Please try again.")
            return
        
        # Generate a unique callback ID for this target
        callback_id = str(uuid.uuid4())[:8]  # Generate unique 8-char ID
        deadline_callbacks[callback_id] = target_id  # Map callback ID to actual target ID
        
        # Ask for deadline with unique callback IDs
        keyboard = [
            [
                InlineKeyboardButton("1 day", callback_data=f"deadline_{callback_id}_1"),
                InlineKeyboardButton("3 days", callback_data=f"deadline_{callback_id}_3"),
                InlineKeyboardButton("7 days", callback_data=f"deadline_{callback_id}_7"),
            ],
            [InlineKeyboardButton("No deadline", callback_data=f"deadline_{callback_id}_0")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ Target set successfully!\n\n"
            f"📝 Target: {target_text}\n"
            f"🆔 Target ID: {target_id[:8]}...\n\n"
            "Would you like to set a deadline?",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error setting target: {e}")
        await update.message.reply_text(
            "❌ An error occurred while setting your target. Please try again."
        )

# Deadline callback handler - FIXED VERSION
async def deadline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle deadline selection - Fixed to work with callback mapping"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    if len(data) != 3:
        await query.edit_message_text("❌ Invalid callback data.")
        return
    
    callback_id = data[1]
    days = int(data[2])
    
    # Get the actual target ID from our mapping
    target_id = deadline_callbacks.get(callback_id)
    
    if not target_id:
        await query.edit_message_text("❌ Target not found. Please set the target again.")
        return
    
    if days > 0:
        deadline = datetime.now() + timedelta(days=days)
        success = db.update_target_deadline(target_id, deadline)
        
        if success:
            await query.edit_message_text(
                text=f"⏰ Deadline set for {days} day(s) from now!"
            )
        else:
            await query.edit_message_text(
                text="❌ Failed to set deadline. Please try again."
            )
    else:
        await query.edit_message_text(
            text="✅ Target saved without deadline."
        )
    
    # Clean up the callback mapping after use
    if callback_id in deadline_callbacks:
        del deadline_callbacks[callback_id]

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
            f"   🆔 ID: {str(target['_id'])[:8]}...\n"
        )
        
        if target.get('deadline'):
            deadline = target['deadline'].strftime("%Y-%m-%d")
            message += f"   ⏰ Deadline: {deadline}\n"
        
        message += "\n"
    
    await update.message.reply_text(message)

async def update_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Update target progress - Fixed to handle target ID better"""
    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: /progress <target_id> <percentage>\n"
            "Example: /progress abc123 50\n\n"
            "Note: You can use partial target ID (first 8 characters)"
        )
        return
    
    target_id_partial, progress = context.args[0], context.args[1]
    
    try:
        progress = int(progress)
        if not 0 <= progress <= 100:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a valid percentage (0-100).")
        return
    
    # Get user's targets to find the full ID
    user_id = update.effective_user.id
    targets = db.get_user_targets(user_id)
    
    # Find target by partial ID
    target_id = None
    for target in targets:
        if str(target['_id']).startswith(target_id_partial):
            target_id = str(target['_id'])
            break
    
    if not target_id:
        await update.message.reply_text(
            f"❌ Target with ID '{target_id_partial}' not found.\n"
            f"Use /mytargets to see your targets and their IDs."
        )
        return
    
    success = db.update_target_progress(target_id, progress)
    
    if success:
        await update.message.reply_text(
            f"📊 Progress updated to {progress}%!\n"
            f"Target ID: {target_id[:8]}..."
        )
    else:
        await update.message.reply_text("❌ Target not found or update failed.")

async def mark_completed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark target as completed - Fixed to handle target ID better"""
    if not context.args:
        await update.message.reply_text(
            "Please specify target ID.\n"
            "Example: /completed abc123\n\n"
            "Note: You can use partial target ID (first 8 characters)"
        )
        return
    
    target_id_partial = context.args[0]
    
    # Get user's targets to find the full ID
    user_id = update.effective_user.id
    targets = db.get_user_targets(user_id)
    
    # Find target by partial ID
    target_id = None
    for target in targets:
        if str(target['_id']).startswith(target_id_partial):
            target_id = str(target['_id'])
            break
    
    if not target_id:
        await update.message.reply_text(
            f"❌ Target with ID '{target_id_partial}' not found.\n"
            f"Use /mytargets to see your targets and their IDs."
        )
        return
    
    success = db.complete_target(target_id)
    
    if success:
        await update.message.reply_text(
            f"🎉 Target marked as completed!\n"
            f"Target ID: {target_id[:8]}..."
        )
    else:
        await update.message.reply_text("❌ Target not found.")

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
        "/checkmembers - Admin: Check and register existing members\n"
        "/registeruser - Admin: Manually register a user\n"
        "/help - Show this help message\n\n"
        "Tips:\n"
        "• Set realistic targets\n"
        "• Update progress regularly\n"
        "• Celebrate completed targets!\n"
        "• Use partial target IDs (first 8 characters) for commands"
    )
    
    await update.message.reply_text(help_text)

# Admin command to manually register users
async def register_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to manually register a user"""
    if not is_allowed_group(update.effective_chat.id):
        return
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return
    
    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(
            "Usage: /registeruser <user_id> or reply to user's message with /registeruser"
        )
        return
    
    try:
        if update.message.reply_to_message:
            user_id = update.message.reply_to_message.from_user.id
            username = update.message.reply_to_message.from_user.username or update.message.reply_to_message.from_user.first_name
        else:
            user_id = int(context.args[0])
            username = context.args[1] if len(context.args) > 1 else "Unknown"
        
        # Check if already registered
        if db.is_user_registered(user_id, update.effective_chat.id):
            await update.message.reply_text(
                f"✅ User @{username} (ID: {user_id}) is already registered."
            )
            return
        
        # Register user
        success = db.accept_rules(user_id, update.effective_chat.id)
        
        if success:
            # Unmute user
            await unmute_user(update.effective_chat.id, user_id, context)
            await update.message.reply_text(
                f"✅ User @{username} (ID: {user_id}) has been registered and unmuted."
            )
        else:
            await update.message.reply_text("Failed to register user.")
            
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_chat:
        try:
            await update.effective_chat.send_message(
                "An error occurred. Please try again later."
            )
        except:
            pass

# Heartbeat function
def send_heartbeat():
    """Send periodic heartbeat to keep the bot alive"""
    while True:
        bot_status["last_heartbeat"] = datetime.now()
        # Clean up old callback mappings (older than 1 hour)
        global deadline_callbacks
        current_time = time.time()
        # We don't store timestamps, but we can clean based on count
        # If there are too many entries, remove some
        if len(deadline_callbacks) > 100:
            # Remove first 50 entries (FIFO)
            keys = list(deadline_callbacks.keys())[:50]
            for key in keys:
                del deadline_callbacks[key]
        time.sleep(300)  # Every 5 minutes

# Start Flask server in a separate thread
def start_flask():
    """Start Flask server for health checks"""
    app.run(host='0.0.0.0', port=PORT)

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

# Main function
def main():
    # Update bot status
    bot_status["is_running"] = True
    bot_status["start_time"] = datetime.now()
    bot_status["last_heartbeat"] = datetime.now()
    
    # Start heartbeat thread
    heartbeat_thread = threading.Thread(target=send_heartbeat, daemon=True)
    heartbeat_thread.start()
    
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS, 
        new_member_handler
    ))
    application.add_handler(CommandHandler("checkmembers", check_existing_members))
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
    print(f"Bot status: {bot_status}")
    print(f"Flask server running on port {PORT}")
    
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=False
        )
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Bot stopped with error: {e}")
    finally:
        bot_status["is_running"] = False
        db.close()

if __name__ == '__main__':
    main()