from datetime import datetime, date
from typing import List, Dict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import config

class Utils:
    @staticmethod
    def format_date(d):
        """Format date for display"""
        if isinstance(d, date):
            return d.strftime("%Y-%m-%d")
        elif isinstance(d, datetime):
            return d.strftime("%Y-%m-%d")
        return str(d)
    
    @staticmethod
    def format_target_message(target: Dict, user_info: Dict = None) -> str:
        """Format target message for display"""
        emoji = "✅" if target.get("status") == "completed" else "📝"
        date_str = Utils.format_date(target.get("date", date.today()))
        
        message = f"{emoji} *Target for {date_str}*\n\n"
        message += f"📌 *Target:* {target.get('target', 'No target set')}\n"
        
        if target.get("status") == "completed":
            completed_at = target.get("completed_at", datetime.now())
            if isinstance(completed_at, datetime):
                message += f"✅ *Completed at:* {completed_at.strftime('%H:%M')}\n"
            else:
                message += f"✅ *Completed at:* {completed_at}\n"
        else:
            message += "⏳ *Status:* Pending\n"
        
        if user_info:
            message += f"\n👤 *User:* {user_info.get('first_name', 'Unknown')}"
            if user_info.get('username'):
                message += f" (@{user_info['username']})"
        
        return message
    
    @staticmethod
    def create_leaderboard_message(leaderboard: List[Dict]) -> str:
        """Format leaderboard message"""
        if not leaderboard:
            return "📊 *No data available for leaderboard yet.*\nBe the first to set targets!"
        
        message = "🏆 *Study Leaderboard* 🏆\n\n"
        message += "*Rankings based on completed targets:*\n\n"
        
        for i, entry in enumerate(leaderboard, 1):
            medal = ""
            if i == 1:
                medal = "🥇 "
            elif i == 2:
                medal = "🥈 "
            elif i == 3:
                medal = "🥉 "
            
            username = entry.get("username")
            first_name = entry.get("first_name", "Unknown")
            display_name = f"@{username}" if username else first_name
            
            completed = entry.get('completed_targets', 0)
            
            message += f"{medal}*{i}. {display_name}*\n"
            message += f"   ✅ {completed} target{'s' if completed != 1 else ''} completed\n\n"
        
        message += "\n📅 *Updated:* " + datetime.now().strftime("%Y-%m-%d %H:%M")
        return message
    
    @staticmethod
    def create_stats_message(user_stats: Dict, user_info: Dict) -> str:
        """Format user statistics message"""
        message = f"📊 *Study Statistics*\n\n"
        message += f"👤 *User:* {user_info.get('first_name', 'User')}\n"
        if user_info.get('username'):
            message += f"📱 *Username:* @{user_info['username']}\n"
        
        message += f"\n📈 *30-Day Performance:*\n"
        message += f"✅ *Completed Targets:* {user_stats.get('completed_targets', 0)}\n"
        message += f"📝 *Pending Targets:* {user_stats.get('pending_targets', 0)}\n"
        message += f"🌴 *Days Off:* {user_stats.get('dayoffs', 0)}\n"
        message += f"🎯 *Completion Rate:* {user_stats.get('completion_rate', 0)}%\n"
        message += f"🔥 *Current Streak:* {user_stats.get('current_streak', 0)} days\n"
        message += f"📅 *Active Study Days:* {user_stats.get('active_days', 0)}/30\n"
        
        # Add motivational message based on stats
        completion_rate = user_stats.get('completion_rate', 0)
        if completion_rate >= 80:
            message += "\n🌟 *Excellent!* Keep up the great work!"
        elif completion_rate >= 50:
            message += "\n💪 *Good progress!* You're doing well!"
        else:
            message += "\n📚 *Keep going!* Consistency is key to success!"
        
        return message
    
    @staticmethod
    def create_registration_keyboard():
        """Create registration acceptance keyboard"""
        keyboard = [
            [
                InlineKeyboardButton("✅ Accept Declaration", callback_data="accept_declaration"),
            ],
            [
                InlineKeyboardButton("📖 Read Rules First", url=config.Config.GROUP_LINK),
                InlineKeyboardButton("❌ Decline", callback_data="decline_declaration")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_declaration_text():
        """Get declaration text for registration"""
        return """
📜 *Study Group Declaration*

*By accepting this declaration, you agree to:*

1. **Daily Participation**: Set study targets daily using `/mytarget`
2. **Honesty**: Only mark targets as completed when actually done
3. **Respect**: Maintain a positive learning environment for all
4. **Communication**: Use `/addoff` when taking breaks with proper reason
5. **No Spam**: Avoid irrelevant messages in the study group
6. **Active Learning**: Engage constructively in study discussions

*Consequences of Non-Compliance:*
- 3 consecutive days without target = Warning
- 4+ consecutive days without target = Temporary removal
- Spamming = Immediate removal
- Harassment = Permanent ban

*Benefits of Participation:*
- Track your study progress
- Compete on leaderboard
- Improve consistency
- Join a supportive community

*Do you accept these terms and conditions?*
        """
