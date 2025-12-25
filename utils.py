from datetime import datetime, date, timedelta
from typing import List, Dict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class Utils:
    @staticmethod
    def format_target_message(target: Dict, user_info: Dict = None) -> str:
        """Format target message for display"""
        emoji = "✅" if target.get("status") == "completed" else "📝"
        date_str = target.get("date", date.today()).strftime("%Y-%m-%d")
        
        message = f"{emoji} *Target for {date_str}*\n\n"
        message += f"📌 *Target:* {target.get('target', 'No target set')}\n"
        
        if target.get("status") == "completed":
            completed_at = target.get("completed_at", datetime.now())
            message += f"✅ *Completed at:* {completed_at.strftime('%H:%M')}\n"
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
            return "📊 *No data available for leaderboard yet.*"
        
        message = "🏆 *Study Leaderboard* 🏆\n\n"
        
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
            
            message += f"{medal}*{i}. {display_name}*\n"
            message += f"   ✅ {entry.get('completed_targets', 0)} targets completed\n\n"
        
        return message
    
    @staticmethod
    def create_stats_message(user_stats: Dict, user_info: Dict) -> str:
        """Format user statistics message"""
        message = f"📊 *Study Statistics for {user_info.get('first_name', 'User')}*\n\n"
        message += f"✅ *Completed Targets:* {user_stats.get('completed_targets', 0)}\n"
        message += f"📝 *Pending Targets:* {user_stats.get('pending_targets', 0)}\n"
        message += f"🌴 *Days Off:* {user_stats.get('dayoffs', 0)}\n"
        message += f"📈 *Completion Rate:* {user_stats.get('completion_rate', 0)}%\n"
        message += f"🔥 *Current Streak:* {user_stats.get('current_streak', 0)} days\n"
        message += f"📅 *Active Study Days:* {user_stats.get('active_days', 0)}\n"
        
        return message
    
    @staticmethod
    def create_registration_keyboard():
        """Create registration acceptance keyboard"""
        keyboard = [
            [
                InlineKeyboardButton("✅ Accept Declaration", callback_data="accept_declaration"),
                InlineKeyboardButton("❌ Decline", callback_data="decline_declaration")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_declaration_text():
        """Get declaration text for registration"""
        return """
📜 *Study Group Declaration*

By accepting this declaration, you agree to:

1. 🤝 *Respect all members* and maintain a positive learning environment
2. 📚 *Set daily study targets* and work towards achieving them
3. ⏰ *Update your progress* regularly in the group
4. 📝 *Use /addoff* when taking a break with proper reason
5. 🚫 *No spam* or irrelevant messages in the group
6. 🔒 *Keep discussions* related to studies and learning

*Failure to comply may result in removal from the group.*

Do you accept these terms and conditions?
        """
