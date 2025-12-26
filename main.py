import os
import logging
import threading
import time
import asyncio
import uuid
from typing import Dict, List
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)
from database import MongoDB
from flask import Flask, jsonify

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ALLOWED_GROUP_ID = os.getenv('ALLOWED_GROUP_ID')
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID')
MONGODB_URI = os.getenv('MONGODB_URI')
PORT = int(os.getenv('PORT', 10000))

# Notification times (24-hour format)
NOTIFICATION_TIMES = [9, 12, 15, 17]  # 9 AM, 12 PM, 3 PM, 5 PM

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

# COMPATIBLE MUTE FUNCTION - Works with older python-telegram-bot versions
async def mute_user(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE, reason: str = "Not registered") -> bool:
    """Mute a user in the group - COMPATIBLE VERSION"""
    try:
        # Log the attempt
        logger.info(f"Attempting to mute user {user_id} in chat {chat_id} for: {reason}")
        
        # Try different permission formats for compatibility
        try:
            # Try new version format (python-telegram-bot >= 13.0)
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
        except TypeError as e:
            if "can_send_media_messages" in str(e):
                # Fallback to older version format
                logger.info("Using older ChatPermissions format (no can_send_media_messages)")
                permissions = ChatPermissions(
                    can_send_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False
                )
            else:
                raise e
        
        # Try to restrict the user
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=datetime.now() + timedelta(days=7)  # 7 days mute
        )
        
        logger.info(f"✅ Successfully muted user {user_id} in group {chat_id}")
        return True
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Failed to mute user {user_id}: {error_msg}")
        
        # Check for common errors
        if "administrator" in error_msg.lower() or "not enough rights" in error_msg.lower():
            logger.error("⚠️ Bot needs admin permissions with 'Restrict members' rights!")
            logger.error("⚠️ Please go to group settings → Administrators → Add bot as admin")
            logger.error("⚠️ Required permissions: 'Delete messages' and 'Restrict members'")
        
        return False

# COMPATIBLE UNMUTE FUNCTION
async def unmute_user(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Unmute a user in the group - COMPATIBLE VERSION"""
    try:
        # Try different permission formats for compatibility
        try:
            # Try new version format
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
        except TypeError as e:
            if "can_send_media_messages" in str(e):
                # Fallback to older version format
                logger.info("Using older ChatPermissions format for unmute")
                permissions = ChatPermissions(
                    can_send_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_change_info=False,
                    can_invite_users=True,
                    can_pin_messages=False
                )
            else:
                raise e
        
        # Restore permissions
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions
        )
        
        logger.info(f"✅ Successfully unmuted user {user_id} in group {chat_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to unmute user {user_id}: {str(e)}")
        return False

# Check if bot has admin permissions
async def check_bot_admin_status(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    """Check if bot has admin permissions"""
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        is_admin = bot_member.status in ['administrator', 'creator']
        logger.info(f"Bot admin status in chat {chat_id}: {is_admin}")
        return is_admin
    except Exception as e:
        logger.error(f"Error checking bot admin status: {e}")
        return False

# Send registration prompt
async def send_registration_prompt(chat_id: int, user_id: int, username: str, context: ContextTypes.DEFAULT_TYPE, registration_id: str = None) -> bool:
    """Send registration prompt to user"""
    try:
        logger.info(f"Sending registration prompt to user {user_id} ({username})")
        
        # If no registration_id provided, create one
        if not registration_id:
            registration_id = db.add_registration(user_id, chat_id, username)
            if not registration_id:
                logger.error(f"Failed to create registration for user {user_id}")
                return False
            logger.info(f"Created new registration with ID: {registration_id}")
        
        # Create the registration button
        keyboard = [[
            InlineKeyboardButton(
                "📝 Register Now", 
                url=f"https://t.me/{context.bot.username}?start=register_{registration_id}"
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Create welcome message
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
        
        # Try to send message in group
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=welcome_message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            logger.info(f"✅ Registration prompt sent to group for user {user_id}")
            return True
        except Exception as group_error:
            logger.error(f"Failed to send registration prompt in group: {group_error}")
            
            # Try to send as a reply instead
            try:
                # Try to get the last message in chat to reply to
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"@{username}, please complete registration to participate!\n\nClick the button below:",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                logger.info(f"✅ Registration prompt sent as reply for user {user_id}")
                return True
            except Exception as reply_error:
                logger.error(f"Failed to send reply registration prompt: {reply_error}")
                return False
                
    except Exception as e:
        logger.error(f"Failed to send registration prompt to {user_id}: {e}")
        return False

# Handler for new members joining the group
async def new_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new members joining the group"""
    try:
        if not is_allowed_group(update.effective_chat.id):
            return
        
        if update.effective_chat.type not in ['group', 'supergroup']:
            return
        
        logger.info(f"New member(s) joined group {update.effective_chat.id}")
        
        for member in update.message.new_chat_members:
            user_id = member.id
            username = member.username or member.first_name
            
            # Skip if it's the bot itself
            if member.id == context.bot.id:
                logger.info("Bot itself joined, skipping")
                continue
            
            logger.info(f"Processing new member: {username} (ID: {user_id})")
            
            # Track member in database
            db.add_group_member(user_id, update.effective_chat.id, username)
            
            # Check if user is already registered
            if db.is_user_registered(user_id, update.effective_chat.id):
                await update.message.reply_text(
                    f"Welcome back, @{username}! You're already registered."
                )
                logger.info(f"User {username} is already registered")
                continue
            
            # Mute the new member
            mute_success = await mute_user(
                update.effective_chat.id, 
                user_id, 
                context, 
                "New member registration required"
            )
            
            if mute_success:
                logger.info(f"✅ New member {username} muted successfully")
                
                # Send registration prompt
                prompt_sent = await send_registration_prompt(
                    update.effective_chat.id, 
                    user_id, 
                    username, 
                    context
                )
                
                if prompt_sent:
                    logger.info(f"✅ Registration prompt sent to {username}")
                else:
                    logger.error(f"❌ Failed to send registration prompt to {username}")
                    
            else:
                logger.error(f"❌ Failed to mute new member {username}")
                # Still try to send registration prompt even if mute failed
                await send_registration_prompt(
                    update.effective_chat.id, 
                    user_id, 
                    username, 
                    context
                )
                
    except Exception as e:
        logger.error(f"Error in new_member_handler: {e}")

# Handler for ALL messages - CHECK AND MUTE UNREGISTERED USERS
async def check_and_mute_unregistered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check all messages and mute unregistered users"""
    try:
        # Skip if no message
        if not update.message or not update.message.text:
            return
        
        # Skip if it's a command (start with '/')
        if update.message.text.startswith('/'):
            return
        
        # Check group
        if not is_allowed_group(update.effective_chat.id):
            return
        
        if update.effective_chat.type not in ['group', 'supergroup']:
            return
        
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        username = update.effective_user.username or update.effective_user.first_name
        
        # Skip admin and bot itself
        if is_admin(str(user_id)):
            logger.info(f"Admin {username} sent message, skipping")
            return
        
        if user_id == context.bot.id:
            return
        
        logger.info(f"Checking message from user {username} (ID: {user_id})")
        
        # Check if user is registered
        if not db.is_user_registered(user_id, chat_id):
            logger.warning(f"User {username} is not registered!")
            
            # Try to mute the user
            mute_success = await mute_user(chat_id, user_id, context, "Unregistered user sent message")
            
            if mute_success:
                logger.info(f"✅ Muted unregistered user {username}")
            
            # Get or create registration
            registration = db.get_registration_status(user_id, chat_id)
            if not registration:
                registration_id = db.add_registration(user_id, chat_id, username)
                logger.info(f"Created registration record for user {username}: {registration_id}")
            else:
                registration_id = str(registration.get('_id', ''))
                logger.info(f"Found existing registration for user {username}")
            
            # Send registration prompt
            await send_registration_prompt(
                chat_id,
                user_id,
                username,
                context,
                registration_id
            )
            
            # Try to delete the user's message
            try:
                await update.message.delete()
                logger.info(f"✅ Deleted message from unregistered user {username}")
            except Exception as delete_error:
                logger.warning(f"Could not delete message: {delete_error}")
                
        else:
            logger.info(f"User {username} is registered, allowing message")
            
    except Exception as e:
        logger.error(f"Error in check_and_mute_unregistered: {e}")

# Command to check and register existing members
async def check_existing_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check existing members and register those who aren't"""
    if not is_allowed_group(update.effective_chat.id):
        return
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return
    
    await update.message.reply_text("🔍 Checking existing members...")
    
    unregistered_members = db.check_and_register_existing_members(
        update.effective_chat.id, 
        context
    )
    
    if not unregistered_members:
        await update.message.reply_text("✅ All members are already registered!")
        return
    
    processed = 0
    for member in unregistered_members:
        try:
            chat_member = await context.bot.get_chat_member(
                update.effective_chat.id,
                member["user_id"]
            )
            
            username = chat_member.user.username or chat_member.user.first_name
            
            await mute_user(
                update.effective_chat.id, 
                member["user_id"], 
                context, 
                "Existing member registration required"
            )
            
            await send_registration_prompt(
                update.effective_chat.id,
                member["user_id"],
                username,
                context,
                member["registration_id"]
            )
            
            processed += 1
            time.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Error processing member {member['user_id']}: {e}")
            continue
    
    await update.message.reply_text(
        f"✅ Processed {processed} unregistered members.\n"
        f"They have been muted and sent registration prompts."
    )

# Send daily reminder notifications
async def send_daily_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Send daily reminders to users who haven't uploaded targets"""
    try:
        today = date.today()
        current_hour = datetime.now().hour
        
        notification_types = {
            9: "first",
            12: "second", 
            15: "third",
            17: "final"
        }
        
        notification_type = notification_types.get(current_hour)
        if not notification_type:
            return
        
        logger.info(f"Sending {notification_type} daily reminder at {current_hour}:00")
        
        users_without_target = db.get_users_without_target_today(today)
        
        if not users_without_target:
            logger.info("All users have uploaded targets today.")
            return
        
        sent_count = 0
        failed_count = 0
        
        for user in users_without_target:
            try:
                notifications_sent = user.get("notifications_sent", [])
                if any(n.get("type") == notification_type for n in notifications_sent):
                    continue
                
                message_text = ""
                if notification_type == "first":
                    message_text = (
                        "📢 **Good Morning!**\n\n"
                        "This is your first reminder to upload your daily study target.\n\n"
                        "Please set your target using:\n"
                        "`/settarget <your target description>`\n\n"
                        "⏰ **Reminder Schedule:**\n"
                        "• 9 AM: First reminder (this one)\n"
                        "• 12 PM: Second reminder\n"
                        "• 3 PM: Third reminder\n"
                        "• 5 PM: Final reminder & absent marking\n\n"
                        "Don't forget to set your target! 📚"
                    )
                elif notification_type == "second":
                    message_text = (
                        "📢 **Midday Reminder!**\n\n"
                        "This is your second reminder to upload your daily study target.\n\n"
                        "Please set your target using:\n"
                        "`/settarget <your target description>`\n\n"
                        "⏰ **Remaining Schedule:**\n"
                        "• 3 PM: Third reminder\n"
                        "• 5 PM: Final reminder & absent marking\n\n"
                        "Please don't delay! ⏳"
                    )
                elif notification_type == "third":
                    message_text = (
                        "📢 **Afternoon Reminder!**\n\n"
                        "This is your third reminder to upload your daily study target.\n\n"
                        "Please set your target using:\n"
                        "`/settarget <your target description>`\n\n"
                        "⚠️ **Final Warning:**\n"
                        "• 5 PM: Final reminder & absent marking\n\n"
                        "This is your last chance before being marked absent! 🚨"
                    )
                elif notification_type == "final":
                    message_text = (
                        "📢 **FINAL REMINDER!**\n\n"
                        "This is your final reminder to upload your daily study target.\n\n"
                        "You have until the end of the day to set your target using:\n"
                        "`/settarget <your target description>`\n\n"
                        "🚨 **IMPORTANT:**\n"
                        "If you don't set a target by the end of today, you will be marked as **ABSENT**.\n\n"
                        "This is your last chance! ⚠️"
                    )
                
                await context.bot.send_message(
                    chat_id=user["user_id"],
                    text=message_text,
                    parse_mode='Markdown'
                )
                
                db.record_notification_sent(user["user_id"], today, notification_type)
                
                sent_count += 1
                logger.info(f"Sent {notification_type} reminder to user {user['user_id']}")
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                failed_count += 1
                logger.error(f"Failed to send reminder to user {user['user_id']}: {e}")
                continue
        
        logger.info(f"Sent {sent_count} reminders, failed: {failed_count}")
        
        if notification_type == "final":
            await mark_absent_users(context, today)
            
    except Exception as e:
        logger.error(f"Error in daily reminders: {e}")

# Mark users as absent
async def mark_absent_users(context: ContextTypes.DEFAULT_TYPE, today: date):
    """Mark users as absent who haven't uploaded targets"""
    try:
        logger.info("Marking absent users for today...")
        
        users_without_target = db.get_users_without_target_today(today)
        
        if not users_without_target:
            logger.info("No users to mark as absent.")
            return
        
        absent_count = 0
        for user in users_without_target:
            try:
                db.mark_user_absent(
                    user["user_id"], 
                    today, 
                    "No daily target submitted"
                )
                
                absent_message = (
                    "📋 **Daily Attendance Report**\n\n"
                    "❌ You have been marked as **ABSENT** for today.\n\n"
                    "**Reason:** No daily study target submitted.\n\n"
                    "**Reminder:** Please make sure to set your daily target before 5 PM tomorrow to avoid being marked absent again.\n\n"
                    "To set a target, use:\n"
                    "`/settarget <your target description>`\n\n"
                    "Stay consistent with your studies! 📚"
                )
                
                await context.bot.send_message(
                    chat_id=user["user_id"],
                    text=absent_message,
                    parse_mode='Markdown'
                )
                
                absent_count += 1
                logger.info(f"Marked user {user['user_id']} as absent")
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Failed to mark user {user['user_id']} as absent: {e}")
                continue
        
        # Send summary to admin
        try:
            admin_message = (
                f"📊 **Daily Attendance Summary**\n\n"
                f"**Date:** {today.strftime('%Y-%m-%d')}\n"
                f"**Total Absent:** {absent_count}\n"
                f"**Total Present:** {len(users_without_target) - absent_count}\n\n"
                f"Absent marking completed successfully. ✅"
            )
            
            await context.bot.send_message(
                chat_id=int(ADMIN_USER_ID),
                text=admin_message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send admin summary: {e}")
        
        logger.info(f"Marked {absent_count} users as absent for {today}")
        
    except Exception as e:
        logger.error(f"Error marking absent users: {e}")

# Command to check daily status
async def daily_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check user's daily status"""
    if not is_allowed_group(update.effective_chat.id):
        return
    
    user_id = update.effective_user.id
    today = date.today()
    
    status = db.get_user_daily_status(user_id, today)
    
    user_targets = db.get_user_targets(user_id)
    today_targets = [
        target for target in user_targets 
        if target.get("created_at") and target["created_at"].date() == today
    ]
    
    message = f"📊 **Daily Status for {today.strftime('%Y-%m-%d')}**\n\n"
    
    if status["has_target"] or today_targets:
        message += "✅ **Status:** PRESENT\n"
        message += f"📚 **Targets Today:** {len(today_targets)}\n\n"
        
        if today_targets:
            message += "**Your targets today:**\n"
            for i, target in enumerate(today_targets[:3], 1):
                progress = target.get("progress", 0)
                message += f"{i}. {target['target'][:50]}... - {progress}%\n"
            
            if len(today_targets) > 3:
                message += f"... and {len(today_targets) - 3} more\n"
    else:
        message += "❌ **Status:** NO TARGET YET\n\n"
        
        notifications = status.get("notifications_sent", [])
        if notifications:
            message += "**Reminders received:**\n"
            for note in notifications[-3:]:
                note_time = note.get("sent_at", datetime.now())
                if isinstance(note_time, str):
                    note_time = datetime.fromisoformat(note_time)
                message += f"• {note_time.strftime('%I:%M %p')} - {note['type'].title()} reminder\n"
        
        if status["marked_absent"]:
            message += f"\n⚠️ **Absent Marked:** {status['absent_reason']}\n"
        else:
            current_hour = datetime.now().hour
            next_reminder = None
            
            for hour in NOTIFICATION_TIMES:
                if hour > current_hour:
                    next_reminder = hour
                    break
            
            if next_reminder:
                message += f"\n⏰ **Next reminder:** {next_reminder}:00\n"
    
    message += "\n---\n"
    message += "**Commands:**\n"
    message += "• `/settarget <description>` - Set daily target\n"
    message += "• `/mytargets` - View all your targets\n"
    message += "• `/dailystatus` - Check this status again\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

# Admin command to view daily attendance
async def attendance_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: View daily attendance report"""
    if not is_allowed_group(update.effective_chat.id):
        return
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return
    
    today = date.today()
    
    registered_users = list(db.registrations.find(
        {"group_id": int(ALLOWED_GROUP_ID), "status": "accepted"}
    ))
    
    if not registered_users:
        await update.message.reply_text("No registered users found.")
        return
    
    present_count = 0
    absent_count = 0
    
    attendance_list = []
    
    for user in registered_users:
        user_id = user["user_id"]
        username = user.get("username", "Unknown")
        
        status = db.get_user_daily_status(user_id, today)
        
        user_targets = db.get_user_targets(user_id)
        has_target_today = any(
            target.get("created_at") and target["created_at"].date() == today
            for target in user_targets
        )
        
        if has_target_today or status["has_target"]:
            status_text = "✅ PRESENT"
            present_count += 1
        elif status["marked_absent"]:
            status_text = "❌ ABSENT"
            absent_count += 1
        else:
            status_text = "⏳ PENDING"
        
        attendance_list.append(f"{status_text} - @{username}")
    
    report = (
        f"📊 **Daily Attendance Report**\n\n"
        f"**Date:** {today.strftime('%Y-%m-%d')}\n"
        f"**Total Users:** {len(registered_users)}\n"
        f"**✅ Present:** {present_count}\n"
        f"**❌ Absent:** {absent_count}\n"
        f"**⏳ Pending:** {len(registered_users) - present_count - absent_count}\n\n"
        f"**Attendance List:**\n"
    )
    
    for i, entry in enumerate(attendance_list[:20], 1):
        report += f"{i}. {entry}\n"
    
    if len(attendance_list) > 20:
        report += f"\n... and {len(attendance_list) - 20} more users\n"
    
    report += f"\n**Next reminder:** {NOTIFICATION_TIMES[0]}:00 AM"
    
    await update.message.reply_text(report, parse_mode='Markdown')

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    if context.args and context.args[0].startswith('register_'):
        registration_id = context.args[0].replace('register_', '')
        
        rules_message = (
            "📋 **Group Rules Declaration**\n\n"
            "Please read and accept the following rules:\n\n"
            "1. **Respect All Members**: Be polite and respectful to everyone.\n"
            "2. **No Spam**: Do not post irrelevant content or advertisements.\n"
            "3. **Study Focus**: Keep discussions related to learning and studies.\n"
            "4. **No Harassment**: Any form of harassment will result in immediate ban.\n"
            "5. **Follow Guidelines**: Adhere to group-specific guidelines.\n"
            "6. **Help Others**: Share knowledge and help fellow students.\n"
            "7. **Report Issues**: Report any problems to admins.\n"
            "8. **Daily Targets**: Upload your study target every day before 5 PM.\n\n"
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
    
    if update.effective_chat.type == 'private':
        welcome_message = (
            f"👋 Hello {user.first_name}!\n\n"
            "I'm the Study Bot. I help manage study targets and group registrations.\n\n"
            "**Daily Target System:**\n"
            "• 9 AM: First reminder\n"
            "• 12 PM: Second reminder\n"
            "• 3 PM: Third reminder\n"
            "• 5 PM: Final reminder & absent marking\n\n"
            "**Important:** Upload your daily target before 5 PM to avoid being marked absent.\n\n"
            "If you were asked to register for a group, please use the registration link provided in the group.\n\n"
            "Commands available in group:\n"
            "/settarget - Set a new study target\n"
            "/mytargets - View your current targets\n"
            "/progress - Update target progress\n"
            "/completed - Mark target as completed\n"
            "/stats - View your study statistics\n"
            "/dailystatus - Check your daily attendance status\n"
            "/help - Show help message"
        )
        await update.message.reply_text(welcome_message)
    elif is_allowed_group(update.effective_chat.id):
        welcome_message = (
            f"🎯 Welcome {user.first_name} to Study Target Bot!\n\n"
            "**📢 IMPORTANT DAILY REMINDERS:**\n"
            "• 9 AM: First reminder\n"
            "• 12 PM: Second reminder\n"
            "• 3 PM: Third reminder\n"
            "• 5 PM: Final reminder & absent marking\n\n"
            "**⚠️ You must upload your daily study target before 5 PM to avoid being marked absent.**\n\n"
            "📚 Available Commands:\n"
            "/settarget - Set a new study target\n"
            "/mytargets - View your current targets\n"
            "/progress - Update target progress\n"
            "/completed - Mark target as completed\n"
            "/stats - View your study statistics\n"
            "/dailystatus - Check your daily status\n"
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
    
    success = db.accept_rules(user_id, int(ALLOWED_GROUP_ID))
    
    if success:
        await unmute_user(int(ALLOWED_GROUP_ID), user_id, context)
        
        await query.edit_message_text(
            "✅ **Registration Successful!**\n\n"
            "You have been unmuted in the group.\n"
            "You can now participate in discussions.\n\n"
            "**📢 IMPORTANT:**\n"
            "• You must upload a daily study target before 5 PM\n"
            "• Reminders will be sent at 9 AM, 12 PM, 3 PM, and 5 PM\n"
            "• Missing targets will result in being marked absent\n\n"
            "Welcome to our study community! 🎓",
            parse_mode='Markdown'
        )
        
        try:
            await context.bot.send_message(
                chat_id=int(ALLOWED_GROUP_ID),
                text=f"🎉 Welcome @{query.from_user.username or query.from_user.first_name} to our study group!\n"
                     "Your registration is complete. Happy studying! 📚\n\n"
                     "**Reminder:** Don't forget to upload your daily study target!"
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
    
    if not db.is_user_registered(user_id, chat_id):
        registration = db.get_registration_status(user_id, chat_id)
        
        if not registration:
            username = update.effective_user.username or update.effective_user.first_name
            registration_id = db.add_registration(user_id, chat_id, username)
        else:
            registration_id = str(registration.get('_id', ''))
        
        await mute_user(chat_id, user_id, context, "Tried to use commands without registration")
        
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
    
    await command_func(update, context)

# Store temporary callback data for deadline buttons
deadline_callbacks = {}

# Set target command
async def set_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set a new study target"""
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
    
    try:
        target_id = db.add_target(target_data)
        
        if not target_id:
            await update.message.reply_text("❌ Failed to save target. Please try again.")
            return
        
        callback_id = str(uuid.uuid4())[:8]
        deadline_callbacks[callback_id] = target_id
        
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

# Deadline callback handler
async def deadline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle deadline selection"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    if len(data) != 3:
        await query.edit_message_text("❌ Invalid callback data.")
        return
    
    callback_id = data[1]
    days = int(data[2])
    
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
    """Update target progress"""
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
    
    user_id = update.effective_user.id
    targets = db.get_user_targets(user_id)
    
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
    """Mark target as completed"""
    if not context.args:
        await update.message.reply_text(
            "Please specify target ID.\n"
            "Example: /completed abc123\n\n"
            "Note: You can use partial target ID (first 8 characters)"
        )
        return
    
    target_id_partial = context.args[0]
    
    user_id = update.effective_user.id
    targets = db.get_user_targets(user_id)
    
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
    
    today = date.today()
    daily_status = db.get_user_daily_status(user_id, today)
    
    attendance_status = "✅ Present" if daily_status["has_target"] else "❌ No target yet"
    if daily_status["marked_absent"]:
        attendance_status = "🚫 Absent"
    
    message = (
        f"📊 Study Statistics for @{update.effective_user.username or update.effective_user.first_name}\n\n"
        f"🎯 Total Targets: {stats['total_targets']}\n"
        f"✅ Completed: {stats['completed_targets']}\n"
        f"⏳ Active: {stats['active_targets']}\n"
        f"📈 Completion Rate: {stats['completion_rate']}%\n"
        f"🔥 Current Streak: {stats['current_streak']} days\n"
        f"🏆 Best Streak: {stats['best_streak']} days\n\n"
        f"📅 **Today's Status ({today.strftime('%Y-%m-%d')}):**\n"
        f"• Attendance: {attendance_status}\n"
        f"• Reminders: {len(daily_status['notifications_sent'])}/4\n"
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
        "**Daily Target System:**\n"
        "• 9 AM: First reminder\n"
        "• 12 PM: Second reminder\n"
        "• 3 PM: Third reminder\n"
        "• 5 PM: Final reminder & absent marking\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/settarget <description> - Set a new study target\n"
        "/mytargets - View your current targets\n"
        "/progress <id> <percentage> - Update target progress\n"
        "/completed <id> - Mark target as completed\n"
        "/stats - View your study statistics\n"
        "/dailystatus - Check your daily attendance status\n"
        "/attendance - Admin: View daily attendance report\n"
        "/export - Admin: Export all data (admin only)\n"
        "/checkmembers - Admin: Check and register existing members\n"
        "/registeruser - Admin: Manually register a user\n"
        "/help - Show this help message\n\n"
        "**Tips:**\n"
        "• Set realistic targets\n"
        "• Update progress regularly\n"
        "• Upload daily target before 5 PM\n"
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
        
        if db.is_user_registered(user_id, update.effective_chat.id):
            await update.message.reply_text(
                f"✅ User @{username} (ID: {user_id}) is already registered."
            )
            return
        
        success = db.accept_rules(user_id, update.effective_chat.id)
        
        if success:
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

# Setup job queue for daily reminders
def setup_job_queue(application):
    """Setup job queue for daily reminders"""
    job_queue = application.job_queue
    
    if job_queue:
        # Schedule reminders at specified times
        for hour in NOTIFICATION_TIMES:
            job_queue.run_daily(
                send_daily_reminders,
                time=datetime.strptime(f"{hour:02d}:00", "%H:%M").time(),
                days=(0, 1, 2, 3, 4, 5, 6)
            )
            logger.info(f"Scheduled daily reminder at {hour}:00")
        
        logger.info("Job queue setup complete")
    else:
        logger.warning("Job queue not available")

# Heartbeat function
def send_heartbeat():
    """Send periodic heartbeat to keep the bot alive"""
    while True:
        bot_status["last_heartbeat"] = datetime.now()
        global deadline_callbacks
        if len(deadline_callbacks) > 100:
            keys = list(deadline_callbacks.keys())[:50]
            for key in keys:
                del deadline_callbacks[key]
        time.sleep(300)

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

async def daily_status_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_registration_and_execute(update, context, daily_status)

async def attendance_report_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_registration_and_execute(update, context, attendance_report)

async def export_data_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_registration_and_execute(update, context, export_data)

async def help_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await check_registration_and_execute(update, context, help_command)

# Test command for manual reminder trigger
async def test_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test command to trigger reminders manually (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return
    
    await update.message.reply_text("🔔 Testing reminder system...")
    await send_daily_reminders(context)
    await update.message.reply_text("✅ Reminder test completed.")

# New command: Check bot admin status
async def bot_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check if bot has admin permissions"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return
    
    chat_id = update.effective_chat.id
    is_bot_admin = await check_bot_admin_status(context, chat_id)
    
    if is_bot_admin:
        await update.message.reply_text("✅ Bot has admin permissions in this group!")
    else:
        await update.message.reply_text(
            "❌ Bot is NOT an admin in this group!\n\n"
            "⚠️ **Please make the bot admin with these permissions:**\n"
            "• Delete messages\n"
            "• Ban users / Restrict members\n"
            "• Invite users via link\n"
            "• Pin messages\n"
            "• Manage video chats\n\n"
            "Without admin rights, the bot cannot:\n"
            "• Mute unregistered users\n"
            "• Delete messages\n"
            "• Manage group properly"
        )

# Test mute command
async def test_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test mute functionality"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    await update.message.reply_text("🔒 Testing mute functionality...")
    
    # Test mute
    mute_success = await mute_user(chat_id, user_id, context, "Test mute")
    
    if mute_success:
        await update.message.reply_text("✅ Mute test successful! You should be muted now.")
        await asyncio.sleep(3)
        
        # Test unmute
        unmute_success = await unmute_user(chat_id, user_id, context)
        
        if unmute_success:
            await update.message.reply_text("✅ Unmute test successful! You should be unmuted now.")
        else:
            await update.message.reply_text("❌ Unmute test failed.")
    else:
        await update.message.reply_text("❌ Mute test failed. Check logs for details.")

# Main function
def main():
    bot_status["is_running"] = True
    bot_status["start_time"] = datetime.now()
    bot_status["last_heartbeat"] = datetime.now()
    
    heartbeat_thread = threading.Thread(target=send_heartbeat, daemon=True)
    heartbeat_thread.start()
    
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    setup_job_queue(application)
    
    # Add handlers - ORDER IS IMPORTANT!
    
    # 1. First handle new members
    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS, 
        new_member_handler
    ))
    
    # 2. Handle all non-command messages to check registration
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        check_and_mute_unregistered
    ))
    
    # 3. Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("checkmembers", check_existing_members))
    application.add_handler(CommandHandler("settarget", set_target_wrapper))
    application.add_handler(CommandHandler("mytargets", my_targets_wrapper))
    application.add_handler(CommandHandler("progress", update_progress_wrapper))
    application.add_handler(CommandHandler("completed", mark_completed_wrapper))
    application.add_handler(CommandHandler("stats", view_stats_wrapper))
    application.add_handler(CommandHandler("dailystatus", daily_status_wrapper))
    application.add_handler(CommandHandler("attendance", attendance_report_wrapper))
    application.add_handler(CommandHandler("export", export_data_wrapper))
    application.add_handler(CommandHandler("help", help_command_wrapper))
    application.add_handler(CommandHandler("testreminder", test_reminder))
    application.add_handler(CommandHandler("botstatus", bot_status_command))
    application.add_handler(CommandHandler("testmute", test_mute))
    application.add_handler(CommandHandler("registeruser", register_user))
    
    # 4. Callback handlers
    application.add_handler(CallbackQueryHandler(deadline_callback, pattern="^deadline_"))
    application.add_handler(CallbackQueryHandler(accept_rules_callback, pattern="^accept_rules_"))
    
    # 5. Error handler
    application.add_error_handler(error_handler)
    
    print("=" * 60)
    print("🤖 Study Bot Starting...")
    print("=" * 60)
    print(f"📱 Bot User ID: {TELEGRAM_TOKEN.split(':')[0]}")
    print(f"🌐 Allowed Group ID: {ALLOWED_GROUP_ID}")
    print(f"👑 Admin User ID: {ADMIN_USER_ID}")
    print(f"🌐 Flask server running on port {PORT}")
    print(f"⏰ Daily reminders at: {', '.join(str(h) + ':00' for h in NOTIFICATION_TIMES)}")
    print("\n⚠️ **CRITICAL:** Make sure bot is ADMIN in your group!")
    print("   Use /botstatus to check admin permissions")
    print("   Use /testmute to test mute functionality")
    print("\n✅ Bot will now:")
    print("   1. Mute new members and send registration prompt")
    print("   2. Mute unregistered users when they send messages")
    print("   3. Delete messages from unregistered users")
    print("   4. Send registration prompts")
    print("=" * 60)
    
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