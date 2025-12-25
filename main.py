import os
import logging
import asyncio
from datetime import datetime, time, timedelta
from typing import Optional, Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode
import config
from database import MongoDB
from utils import Utils

# Initialize
db = MongoDB()
logger = logging.getLogger(__name__)

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Helper functions
def is_admin(user_id: int) -> bool:
    return str(user_id) == str(config.Config.ADMIN_USER_ID)

def is_allowed_group(chat_id: int) -> bool:
    return str(chat_id) == str(config.Config.ALLOWED_GROUP_ID)

def is_command_exempt(text: str) -> bool:
    """Check if message is a command that should be exempt from daily limit"""
    if not text or not text.startswith('/'):
        return False
    
    # Remove bot mention if present
    text = text.split('@')[0] if '@' in text else text
    
    for cmd in config.Config.EXEMPT_COMMANDS:
        if text.startswith(cmd):
            return True
    return False

async def restrict_user_in_group(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Restrict user's permissions in the group"""
    try:
        # Create restricted permissions
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
            chat_id=config.Config.ALLOWED_GROUP_ID,
            user_id=user_id,
            permissions=permissions
        )
        logger.info(f"Restricted user {user_id} in group")
        return True
    except Exception as e:
        logger.error(f"Failed to restrict user {user_id}: {e}")
        return False

async def unrestrict_user_in_group(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Unrestrict user's permissions in the group"""
    try:
        # Restore normal permissions (as per group defaults)
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=False,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False
        )
        
        await context.bot.restrict_chat_member(
            chat_id=config.Config.ALLOWED_GROUP_ID,
            user_id=user_id,
            permissions=permissions
        )
        logger.info(f"Unrestricted user {user_id} in group")
        return True
    except Exception as e:
        logger.error(f"Failed to unrestrict user {user_id}: {e}")
        return False

async def send_welcome_and_restrict(update: Update, context: ContextTypes.DEFAULT_TYPE, new_member):
    """Send welcome message and restrict new user"""
    chat = update.effective_chat
    
    # Create registration keyboard
    keyboard = [[
        InlineKeyboardButton(
            "📝 Register Now",
            url=f"https://t.me/{context.bot.username}?start=register"
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Welcome message
    welcome_msg = (
        f"👋 Welcome {new_member.mention_html()} to the Study Group!\n\n"
        "📚 *Before you can participate, you must:*\n"
        "1. Click the button below to register\n"
        "2. Accept the group declaration\n"
        "3. Get verified by the bot\n\n"
        "⚠️ *Your messages will be restricted until you register.*\n"
        "⏳ You have 24 hours to register or you'll be removed."
    )
    
    await chat.send_message(
        welcome_msg,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )
    
    # Restrict user immediately
    await restrict_user_in_group(context, new_member.id)
    
    # Send DM invitation
    try:
        dm_msg = (
            "👋 Hello! Welcome to our study group.\n\n"
            "To participate in the group, please click the button below "
            "to accept our declaration and register."
        )
        
        await context.bot.send_message(
            chat_id=new_member.id,
            text=dm_msg,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Could not send DM to user {new_member.id}: {e}")

async def check_message_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user has exceeded daily message limit"""
    user = update.effective_user
    chat = update.effective_chat
    
    if not is_allowed_group(chat.id):
        return True
    
    # Check if user is registered
    if not db.is_user_registered(user.id):
        return False
    
    # Check if message is a command and exempt
    if update.message.text and is_command_exempt(update.message.text):
        return True
    
    # Update message count
    current_count, limit = db.update_daily_message_count(user.id)
    
    # Check if limit reached
    if current_count > limit:
        try:
            await update.message.delete()
            warning_msg = (
                f"⚠️ {user.mention_html()}, you've reached your daily message limit ({limit}).\n"
                f"Please wait until tomorrow or ask an admin to extend your limit."
            )
            await chat.send_message(warning_msg, parse_mode=ParseMode.HTML)
        except:
            pass
        return False
    
    # Check if warning threshold reached
    warning_threshold = int(limit * config.Config.WARNING_THRESHOLD)
    if current_count == warning_threshold:
        remaining = limit - current_count
        warning_msg = (
            f"⚠️ {user.mention_html()}, you've used {current_count}/{limit} messages today.\n"
            f"Only {remaining} messages remaining!"
        )
        await chat.send_message(warning_msg, parse_mode=ParseMode.HTML)
    
    return True

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    if update.message.chat.type == "private":  # DM
        if context.args and context.args[0] == "register":
            # Check if already registered
            if db.is_user_registered(user.id):
                await update.message.reply_text(
                    "✅ You are already registered!\n"
                    "You can now participate in the group."
                )
                return
            
            # Send declaration
            await update.message.reply_text(
                Utils.get_declaration_text(),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=Utils.create_registration_keyboard()
            )
        else:
            await update.message.reply_text(
                "🤖 *Study Bot Commands*\n\n"
                "In group:\n"
                "/mytarget - Set today's target (reply to message with image)\n"
                "/complete - Mark today's target as completed\n"
                "/addoff <reason> - Mark today as day off\n"
                "/leaderboard - View top performers\n"
                "/progress - View your statistics\n"
                "/myday - View today's target\n\n"
                "In DM:\n"
                "Use /start register to begin registration",
                parse_mode=ParseMode.MARKDOWN
            )
    else:  # Group chat
        if is_allowed_group(update.effective_chat.id):
            await update.message.reply_text(
                "🤖 *Study Bot is active!*\n\n"
                "Available commands:\n"
                "/mytarget - Set today's target\n"
                "/complete - Mark target completed\n"
                "/addoff <reason> - Take day off\n"
                "/leaderboard - View rankings\n"
                "/progress - Your statistics\n"
                "/myday - Today's target\n"
                "/help - Show all commands",
                parse_mode=ParseMode.MARKDOWN
            )

async def handle_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new members joining the group"""
    chat = update.effective_chat
    
    if not is_allowed_group(chat.id):
        return
    
    for new_member in update.message.new_chat_members:
        # Skip if bot itself
        if new_member.id == context.bot.id:
            continue
        
        # Check if user already exists
        existing_user = db.get_user(new_member.id)
        
        if not existing_user:
            # Add user to database
            db.add_user(
                user_id=new_member.id,
                username=new_member.username,
                first_name=new_member.first_name,
                group_id=chat.id
            )
        
        # Send welcome message and restrict
        await send_welcome_and_restrict(update, context, new_member)

async def mytarget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mytarget command"""
    chat = update.effective_chat
    user = update.effective_user
    
    if not is_allowed_group(chat.id):
        return
    
    # Check if user is registered
    if not db.is_user_registered(user.id):
        keyboard = [[InlineKeyboardButton(
            "📝 Register Now",
            url=f"https://t.me/{context.bot.username}?start=register"
        )]]
        
        await update.message.reply_text(
            "⚠️ Please register first by clicking the button below.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Get target text from command arguments
    if not context.args:
        # Check if replying to a message
        if update.message.reply_to_message:
            # Get text from replied message
            if update.message.reply_to_message.caption:
                target_text = update.message.reply_to_message.caption
            elif update.message.reply_to_message.text:
                target_text = update.message.reply_to_message.text
            else:
                target_text = ""
        else:
            await update.message.reply_text(
                "📝 *How to set target:*\n\n"
                "1. Type your target after the command:\n"
                "   `/mytarget Complete chapter 5 of Physics`\n\n"
                "2. Or reply to an image with the command:\n"
                "   Reply to image with `/mytarget`\n\n"
                "3. Or reply to a text message with the command",
                parse_mode=ParseMode.MARKDOWN
            )
            return
    else:
        target_text = " ".join(context.args)
    
    if not target_text.strip():
        await update.message.reply_text(
            "Please provide target text.\n"
            "Example: `/mytarget Study calculus chapter 3`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Get image if available (from replied message)
    image_id = None
    if update.message.reply_to_message and update.message.reply_to_message.photo:
        image_id = update.message.reply_to_message.photo[-1].file_id
    
    # Save target
    try:
        success = db.add_target(user.id, target_text, image_id)
        
        if success:
            # Prepare response
            response = f"🎯 *Target Set!*\n\n"
            response += f"📌 *Target:* {target_text}\n"
            response += f"👤 *By:* {user.mention_html()}\n"
            
            if image_id:
                response += f"🖼️ *Includes image*"
                # Send photo with caption
                await chat.send_photo(
                    photo=image_id,
                    caption=response,
                    parse_mode=ParseMode.HTML
                )
            else:
                await chat.send_message(response, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(
                "❌ Failed to set target. Please try again.",
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        logger.error(f"Error in mytarget command: {e}")
        await update.message.reply_text(
            "❌ Error setting target. Please try again.",
            parse_mode=ParseMode.MARKDOWN
        )

async def complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /complete command"""
    chat = update.effective_chat
    user = update.effective_user
    
    if not is_allowed_group(chat.id):
        return
    
    # Check if user is registered
    if not db.is_user_registered(user.id):
        await update.message.reply_text(
            "⚠️ Please register first. Use /start in DM to register.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check if user has target for today
    target = db.get_today_target(user.id)
    if not target:
        await update.message.reply_text(
            "📝 You haven't set a target for today!\n"
            "Use `/mytarget` to set one first.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Mark as completed
    success = db.complete_target(user.id)
    
    if success:
        await chat.send_message(
            f"🎉 *Target Completed!*\n\n"
            f"✅ {user.mention_html()} has completed today's target!\n"
            f"📌 Target: {target.get('target', 'No target')}\n"
            f"🕐 Time: {datetime.now().strftime('%H:%M')}",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            "❌ Failed to mark as completed. You may not have a target today.",
            parse_mode=ParseMode.MARKDOWN
        )

async def addoff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addoff command"""
    chat = update.effective_chat
    user = update.effective_user
    
    if not is_allowed_group(chat.id):
        return
    
    # Check if user is registered
    if not db.is_user_registered(user.id):
        await update.message.reply_text(
            "⚠️ Please register first. Use /start in DM to register.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check reason
    reason = " ".join(context.args) if context.args else "Personal reasons"
    
    if len(reason) > 100:
        await update.message.reply_text(
            "Reason too long. Please keep it under 100 characters.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check if already has target for today
    existing_target = db.get_today_target(user.id)
    if existing_target:
        await update.message.reply_text(
            "⚠️ You already have a target set for today.\n"
            "Complete it first with `/complete` or update it with `/mytarget`.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Add day off
    success = db.add_dayoff(user.id, reason)
    
    if success:
        await chat.send_message(
            f"🌴 *Day Off Added*\n\n"
            f"{user.mention_html()} is taking a day off.\n"
            f"📝 Reason: {reason}\n"
            f"📅 Date: {datetime.now().strftime('%Y-%m-%d')}",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            "❌ You've already marked today as day off.",
            parse_mode=ParseMode.MARKDOWN
        )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /leaderboard command"""
    chat = update.effective_chat
    
    if not is_allowed_group(chat.id):
        return
    
    # Get leaderboard
    leaderboard_data = db.get_leaderboard(chat.id)
    
    # Format message
    message = Utils.create_leaderboard_message(leaderboard_data)
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /progress command"""
    chat = update.effective_chat
    user = update.effective_user
    
    if not is_allowed_group(chat.id):
        return
    
    # Check if user is registered
    if not db.is_user_registered(user.id):
        await update.message.reply_text(
            "⚠️ Please register first. Use /start in DM to register.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Get user stats
    user_info = db.get_user(user.id)
    stats = db.get_user_stats(user.id)
    
    # Format message
    message = Utils.create_stats_message(stats, user_info)
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def myday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /myday command"""
    chat = update.effective_chat
    user = update.effective_user
    
    if not is_allowed_group(chat.id):
        return
    
    # Check if user is registered
    if not db.is_user_registered(user.id):
        await update.message.reply_text(
            "⚠️ Please register first. Use /start in DM to register.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check today's target
    target = db.get_today_target(user.id)
    
    if target:
        message = Utils.format_target_message(target, db.get_user(user.id))
        
        # Send with image if available
        if target.get("image_id"):
            await chat.send_photo(
                photo=target["image_id"],
                caption=message,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    else:
        # Check if day off
        if db.has_dayoff_today(user.id):
            await update.message.reply_text(
                "🌴 You have marked today as day off.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "📝 You haven't set a target for today!\n"
                "Use `/mytarget` to set your target.",
                parse_mode=ParseMode.MARKDOWN
            )

async def extend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /extend command (admin only)"""
    chat = update.effective_chat
    user = update.effective_user
    
    if not is_allowed_group(chat.id):
        return
    
    # Check if admin
    if not is_admin(user.id):
        await update.message.reply_text(
            "❌ This command is for admins only.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check arguments
    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: `/extend @username 10`\n"
            "Or: `/extend user_id 10`\n\n"
            "Example: `/extend @john 5` - extends by 5 messages",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        target_user_ref = context.args[0]
        additional_messages = int(context.args[1])
        
        if additional_messages <= 0 or additional_messages > 100:
            await update.message.reply_text(
                "❌ Number must be between 1 and 100.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Find user
        target_user = None
        
        # Check if it's a user ID
        if target_user_ref.isdigit():
            target_user = db.get_user(int(target_user_ref))
        # Check if it's a mention
        elif target_user_ref.startswith('@'):
            username = target_user_ref[1:]  # Remove @
            # Find by username
            all_users = db.get_all_users(chat.id)
            for u in all_users:
                if u.get('username') and u['username'].lower() == username.lower():
                    target_user = u
                    break
        
        if not target_user:
            await update.message.reply_text(
                "❌ User not found.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Extend limit
        success = db.extend_user_limit(target_user['user_id'], additional_messages)
        
        if success:
            new_limit = target_user.get('daily_limit', config.Config.DEFAULT_DAILY_MESSAGE_LIMIT) + additional_messages
            await update.message.reply_text(
                f"✅ Extended {target_user.get('first_name', 'User')}'s "
                f"daily limit by {additional_messages} messages.\n"
                f"New daily limit: {new_limit}",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "❌ Failed to extend limit.",
                parse_mode=ParseMode.MARKDOWN
            )
            
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid number format.",
            parse_mode=ParseMode.MARKDOWN
        )

async def setlimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /setlimit command (admin only)"""
    chat = update.effective_chat
    user = update.effective_user
    
    if not is_allowed_group(chat.id):
        return
    
    # Check if admin
    if not is_admin(user.id):
        await update.message.reply_text(
            "❌ This command is for admins only.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check arguments
    if len(context.args) < 1:
        await update.message.reply_text(
            "Usage: `/setlimit 30`\n"
            "Sets default daily message limit for all group members.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        limit = int(context.args[0])
        
        if limit < 5 or limit > 200:
            await update.message.reply_text(
                "❌ Limit must be between 5 and 200.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Set limit
        success = db.set_group_limit(chat.id, limit)
        
        if success:
            await update.message.reply_text(
                f"✅ Default daily message limit set to {limit} for all users.\n"
                f"Existing users will have this limit on their next message.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "❌ Failed to set limit.",
                parse_mode=ParseMode.MARKDOWN
            )
            
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid number format.",
            parse_mode=ParseMode.MARKDOWN
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """
🤖 *Study Bot Help Guide*

📚 *For Everyone:*
/mytarget - Set today's study target (can include images)
/complete - Mark today's target as completed
/addoff <reason> - Mark today as day off with reason
/leaderboard - View top performers ranking
/progress - View your personal statistics
/myday - View your target for today
/help - Show this help message

👑 *Admin Commands:*
/extend <user> <number> - Extend user's daily message limit
/setlimit <number> - Set default daily limit for group

📋 *Rules:*
• Register via DM before participating
• Set daily targets using /mytarget
• Take day off with /addoff when needed
• Daily message limit: 20 (default)
• 3 consecutive days without target = warning/kick
• Commands don't count towards message limit

❓ *Need Help?* Contact admin.
    """
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def handle_declaration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle declaration acceptance callback"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if query.data == "accept_declaration":
        # Register user
        success = db.register_user(user.id)
        
        if success:
            # Unrestrict user in group
            await unrestrict_user_in_group(context, user.id)
            
            await query.edit_message_text(
                "✅ *Registration Successful!*\n\n"
                "You can now participate in the study group.\n"
                f"Return to group: {config.Config.GROUP_LINK}\n\n"
                "*Remember:*\n"
                "• Set daily targets with `/mytarget`\n"
                "• Mark completed with `/complete`\n"
                "• Use `/addoff` when taking breaks\n"
                "• Daily message limit: 20\n"
                "• Have fun learning! 🎓",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Send welcome message to group
            try:
                await context.bot.send_message(
                    chat_id=config.Config.ALLOWED_GROUP_ID,
                    text=f"👋 Welcome {user.mention_html()} to the study group! 🎉",
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
        else:
            await query.edit_message_text(
                "❌ Registration failed. Please try again or contact admin."
            )
    else:  # decline
        await query.edit_message_text(
            "❌ Registration declined.\n"
            "You must accept the declaration to join the study group."
        )

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all messages to check limits and restrictions"""
    if not update.message:
        return
    
    chat = update.effective_chat
    user = update.effective_user
    
    # Only process group messages
    if not is_allowed_group(chat.id):
        return
    
    # Skip if message is from bot
    if user.id == context.bot.id:
        return
    
    # Get user data
    user_data = db.get_user(user.id)
    if not user_data:
        # Add user if not exists (for manual adds or users who joined before bot)
        db.add_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            group_id=chat.id
        )
        user_data = db.get_user(user.id)
    
    # Check if user is registered
    if not user_data.get("registered", False):
        # Check if message is a command that unregistered users can use
        if update.message.text and update.message.text.startswith('/'):
            cmd = update.message.text.split('@')[0] if '@' in update.message.text else update.message.text
            if cmd in ['/start', '/help']:
                return  # Allow these commands
        
        # Delete message from unregistered user
        try:
            await update.message.delete()
            
            # Send warning only once every 2 minutes per user
            user_key = f"last_warning_{user.id}"
            last_warning = context.user_data.get(user_key, datetime.min)
            if (datetime.now() - last_warning).total_seconds() > 120:  # 2 minutes
                keyboard = [[InlineKeyboardButton(
                    "📝 Register Now",
                    url=f"https://t.me/{context.bot.username}?start=register"
                )]]
                
                warning_msg = (
                    f"⚠️ {user.mention_html()}, please register first!\n"
                    f"Click the button below to register and accept the declaration."
                )
                await chat.send_message(
                    warning_msg,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                context.user_data[user_key] = datetime.now()
        except Exception as e:
            logger.error(f"Error handling unregistered user message: {e}")
        return
    
    # User is registered, check daily message limit
    if not await check_message_limit(update, context):
        return

async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Send reminders to users without targets"""
    job = context.job
    
    # Get users without targets today
    users_without_target = db.get_users_without_target_today(config.Config.ALLOWED_GROUP_ID)
    
    for user in users_without_target:
        user_id = user["user_id"]
        
        try:
            # Send reminder via DM
            reminder_msg = (
                "📢 *Daily Reminder*\n\n"
                "You haven't set your study target for today!\n\n"
                f"📍 Group: {config.Config.GROUP_LINK}\n"
                "📝 Use `/mytarget` to set your target\n"
                "🌴 Or `/addoff <reason>` if taking break\n"
                "✅ Use `/complete` when done\n\n"
                "*Warning:* 3 consecutive days without target may result in removal."
            )
            
            await context.bot.send_message(
                chat_id=user_id,
                text=reminder_msg,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Update last reminder date
            db.users.update_one(
                {"user_id": user_id},
                {"$set": {"last_reminder_date": datetime.now()}}
            )
            
            # Increment absence count
            db.increment_absence(user_id)
            
        except Exception as e:
            logger.error(f"Failed to send reminder to {user_id}: {e}")
            
            # If can't send DM (user blocked bot), increment absence anyway
            db.increment_absence(user_id)

async def check_absent_users(context: ContextTypes.DEFAULT_TYPE):
    """Check and warn/kick users with consecutive absences"""
    job = context.job
    
    # Get users exceeding absence limit
    absent_users = db.get_users_exceeding_absence_limit(
        config.Config.ALLOWED_GROUP_ID,
        config.Config.CONSECUTIVE_ABSENCE_LIMIT
    )
    
    for user in absent_users:
        user_id = user["user_id"]
        consecutive_absence = user.get("consecutive_absence", 0)
        
        # Send warning for 3 consecutive absences
        if consecutive_absence == 3:
            try:
                warning_msg = (
                    f"⚠️ *Warning*\n\n"
                    f"You haven't set targets for {consecutive_absence} consecutive days.\n"
                    f"Please set your target today or you may be removed from the group."
                )
                
                await context.bot.send_message(
                    chat_id=user_id,
                    text=warning_msg,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                logger.info(f"Sent warning to user {user_id} for {consecutive_absence} absences")
                
            except Exception as e:
                logger.error(f"Failed to warn user {user_id}: {e}")

async def reset_daily_counts_job(context: ContextTypes.DEFAULT_TYPE):
    """Reset daily message counts at midnight"""
    db.reset_daily_counts()
    logger.info("Daily message counts reset")

def main():
    """Start the bot"""
    # Create application with job queue
    application = Application.builder().token(config.Config.TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("mytarget", mytarget))
    application.add_handler(CommandHandler("complete", complete))
    application.add_handler(CommandHandler("addoff", addoff))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("progress", progress))
    application.add_handler(CommandHandler("myday", myday))
    application.add_handler(CommandHandler("extend", extend))
    application.add_handler(CommandHandler("setlimit", setlimit))
    application.add_handler(CommandHandler("help", help_command))
    
    # Message handlers
    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        handle_new_chat_members
    ))
    
    # All other messages
    application.add_handler(MessageHandler(
        filters.ALL & filters.ChatType.GROUPS,
        handle_all_messages
    ))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(
        handle_declaration_callback,
        pattern="^(accept|decline)_declaration$"
    ))
    
    # Job queue for scheduled tasks
    job_queue = application.job_queue
    
    if job_queue:
        # Send reminders every day at 10:00 AM
        job_queue.run_daily(
            send_reminders,
            time=config.Config.REMINDER_TIME,
            days=(0, 1, 2, 3, 4, 5, 6),
            name="send_reminders"
        )
        
        # Check absent users every day at 11:00 PM
        job_queue.run_daily(
            check_absent_users,
            time=time(23, 0),
            days=(0, 1, 2, 3, 4, 5, 6),
            name="check_absent_users"
        )
        
        # Reset daily counts at midnight
        job_queue.run_daily(
            reset_daily_counts_job,
            time=time(0, 0),
            days=(0, 1, 2, 3, 4, 5, 6),
            name="reset_daily_counts"
        )
    else:
        logger.warning("Job queue not available. Scheduled tasks will not run.")
    
    # Start the bot
    print("🤖 Study Bot is starting...")
    print(f"📊 Group ID: {config.Config.ALLOWED_GROUP_ID}")
    print(f"👑 Admin ID: {config.Config.ADMIN_USER_ID}")
    print(f"🔗 Group Link: {config.Config.GROUP_LINK}")
    
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()