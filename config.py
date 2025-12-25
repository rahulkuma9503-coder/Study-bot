import os
from datetime import time
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    ALLOWED_GROUP_ID = int(os.getenv('ALLOWED_GROUP_ID'))
    ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID'))
    
    # MongoDB
    MONGODB_URI = os.getenv('MONGODB_URI')
    
    # Limits
    DEFAULT_DAILY_MESSAGE_LIMIT = 20
    WARNING_THRESHOLD = 0.9  # 90%
    CONSECUTIVE_ABSENCE_LIMIT = 3
    
    # Reminder Settings
    REMINDER_INTERVAL_HOURS = 24  # Send reminders every 24 hours
    REMINDER_TIME = time(10, 0)  # 10:00 AM
    
    # Commands not counted in daily limit
    EXEMPT_COMMANDS = [
        '/mytarget',
        '/complete',
        '/addoff',
        '/leaderboard',
        '/progress',
        '/myday',
        '/extend',
        '/setlimit',
        '/help',
        '/start'
    ]
    
    # Group settings
    GROUP_LINK = os.getenv('GROUP_LINK', 'https://t.me/your_group_link')
