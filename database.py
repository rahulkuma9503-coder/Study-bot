from typing import Dict
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Tuple
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
import config

class MongoDB:
    def __init__(self):
        self.client = MongoClient(config.Config.MONGODB_URI)
        self.db = self.client.study_bot
        
        # Collections
        self.users = self.db.users
        self.targets = self.db.targets
        self.dayoffs = self.db.dayoffs
        self.messages = self.db.messages
        self.settings = self.db.settings
        
        self._create_indexes()
    
    def _create_indexes(self):
        # Users collection indexes
        self.users.create_index([("user_id", ASCENDING)], unique=True)
        self.users.create_index([("group_id", ASCENDING)])
        self.users.create_index([("registered", ASCENDING)])
        
        # Targets collection indexes
        self.targets.create_index([("user_id", ASCENDING), ("date", DESCENDING)], unique=True)
        self.targets.create_index([("status", ASCENDING)])
        self.targets.create_index([("date", DESCENDING)])
        
        # Dayoffs collection indexes
        self.dayoffs.create_index([("user_id", ASCENDING), ("date", DESCENDING)], unique=True)
        
        # Messages collection indexes
        self.messages.create_index([("user_id", ASCENDING), ("date", DESCENDING)])
        
        # Settings collection
        self.settings.create_index([("group_id", ASCENDING)], unique=True)
    
    # User Management
    def add_user(self, user_id: int, username: str, first_name: str, group_id: int) -> bool:
        try:
            user_data = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "group_id": group_id,
                "registered": False,
                "restricted": True,
                "daily_limit": config.Config.DEFAULT_DAILY_MESSAGE_LIMIT,
                "messages_today": 0,
                "last_message_date": None,
                "joined_at": datetime.now(),
                "consecutive_absence": 0,
                "warnings": 0
            }
            self.users.insert_one(user_data)
            return True
        except DuplicateKeyError:
            return False
    
    def register_user(self, user_id: int) -> bool:
        result = self.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "registered": True,
                "restricted": False,
                "declaration_accepted": True,
                "declaration_accepted_at": datetime.now()
            }}
        )
        return result.modified_count > 0
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        return self.users.find_one({"user_id": user_id})
    
    def is_user_registered(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        return user and user.get("registered", False) if user else False
    
    def update_daily_message_count(self, user_id: int) -> Tuple[int, int]:
        """Update message count for today, returns (current_count, limit)"""
        today = date.today()
        user = self.get_user(user_id)
        
        if not user:
            return (0, config.Config.DEFAULT_DAILY_MESSAGE_LIMIT)
        
        # Reset counter if it's a new day
        if user.get("last_message_date") != today:
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {"messages_today": 1, "last_message_date": today}}
            )
            return (1, user.get("daily_limit", config.Config.DEFAULT_DAILY_MESSAGE_LIMIT))
        
        # Increment counter
        new_count = user.get("messages_today", 0) + 1
        self.users.update_one(
            {"user_id": user_id},
            {"$set": {"messages_today": new_count, "last_message_date": today}}
        )
        
        return (new_count, user.get("daily_limit", config.Config.DEFAULT_DAILY_MESSAGE_LIMIT))
    
    def extend_user_limit(self, user_id: int, additional_messages: int) -> bool:
        """Extend user's daily message limit"""
        result = self.users.update_one(
            {"user_id": user_id},
            {"$inc": {"daily_limit": additional_messages}}
        )
        return result.modified_count > 0
    
    def set_group_limit(self, group_id: int, limit: int) -> bool:
        """Set default daily limit for group"""
        result = self.settings.update_one(
            {"group_id": group_id},
            {"$set": {"daily_message_limit": limit}},
            upsert=True
        )
        
        # Update all users in the group with new default limit
        if result.upserted_id or result.modified_count > 0:
            self.users.update_many(
                {"group_id": group_id, "daily_limit": config.Config.DEFAULT_DAILY_MESSAGE_LIMIT},
                {"$set": {"daily_limit": limit}}
            )
        return True
    
    def reset_daily_counts(self):
        """Reset all daily message counts (to be called at midnight)"""
        self.users.update_many(
            {},
            {"$set": {"messages_today": 0}}
        )
    
    # Target Management
    def add_target(self, user_id: int, target_text: str, image_id: str = None) -> bool:
        """Add target for today"""
        today = date.today()
        
        try:
            target_data = {
                "user_id": user_id,
                "date": today,
                "target": target_text,
                "image_id": image_id,
                "status": "pending",
                "created_at": datetime.now(),
                "completed_at": None
            }
            self.targets.insert_one(target_data)
            
            # Reset consecutive absence on target submission
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {"consecutive_absence": 0}}
            )
            return True
        except DuplicateKeyError:
            # Update existing target
            self.targets.update_one(
                {"user_id": user_id, "date": today},
                {"$set": {
                    "target": target_text,
                    "image_id": image_id,
                    "updated_at": datetime.now()
                }}
            )
            return True
    
    def complete_target(self, user_id: int) -> bool:
        """Mark today's target as completed"""
        today = date.today()
        result = self.targets.update_one(
            {"user_id": user_id, "date": today},
            {"$set": {
                "status": "completed",
                "completed_at": datetime.now()
            }}
        )
        return result.modified_count > 0
    
    def get_today_target(self, user_id: int) -> Optional[Dict]:
        today = date.today()
        return self.targets.find_one({"user_id": user_id, "date": today})
    
    def get_user_targets(self, user_id: int, days: int = 7) -> List[Dict]:
        """Get user's targets for last N days"""
        start_date = date.today() - timedelta(days=days)
        return list(self.targets.find({
            "user_id": user_id,
            "date": {"$gte": start_date}
        }).sort("date", DESCENDING))
    
    # Day Off Management
    def add_dayoff(self, user_id: int, reason: str) -> bool:
        """Mark today as day off"""
        today = date.today()
        
        try:
            dayoff_data = {
                "user_id": user_id,
                "date": today,
                "reason": reason,
                "created_at": datetime.now()
            }
            self.dayoffs.insert_one(dayoff_data)
            
            # Reset consecutive absence on day off
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {"consecutive_absence": 0}}
            )
            return True
        except DuplicateKeyError:
            return False
    
    def has_dayoff_today(self, user_id: int) -> bool:
        today = date.today()
        return self.dayoffs.find_one({"user_id": user_id, "date": today}) is not None
    
    # Statistics and Reminders
    def get_users_without_target_today(self, group_id: int) -> List[Dict]:
        """Get registered users who haven't set target or taken day off today"""
        today = date.today()
        
        # Get all registered users in group
        all_users = list(self.users.find({
            "group_id": group_id,
            "registered": True
        }))
        
        users_without_target = []
        
        for user in all_users:
            user_id = user["user_id"]
            
            # Check if user has target today
            has_target = self.targets.find_one({"user_id": user_id, "date": today}) is not None
            
            # Check if user has day off today
            has_dayoff = self.has_dayoff_today(user_id)
            
            if not has_target and not has_dayoff:
                users_without_target.append(user)
        
        return users_without_target
    
    def increment_absence(self, user_id: int):
        """Increment consecutive absence count"""
        self.users.update_one(
            {"user_id": user_id},
            {"$inc": {"consecutive_absence": 1}}
        )
    
    def get_users_exceeding_absence_limit(self, group_id: int, limit: int = 3) -> List[Dict]:
        """Get users with consecutive absence >= limit"""
        return list(self.users.find({
            "group_id": group_id,
            "registered": True,
            "consecutive_absence": {"$gte": limit}
        }))
    
    def reset_absence(self, user_id: int):
        """Reset consecutive absence count"""
        self.users.update_one(
            {"user_id": user_id},
            {"$set": {"consecutive_absence": 0}}
        )
    
    # Leaderboard
    def get_leaderboard(self, group_id: int, days: int = 30) -> List[Dict]:
        """Get leaderboard based on completed targets"""
        start_date = date.today() - timedelta(days=days)
        
        pipeline = [
            {
                "$match": {
                    "date": {"$gte": start_date},
                    "status": "completed"
                }
            },
            {
                "$lookup": {
                    "from": "users",
                    "localField": "user_id",
                    "foreignField": "user_id",
                    "as": "user_info"
                }
            },
            {"$unwind": "$user_info"},
            {
                "$match": {
                    "user_info.group_id": group_id,
                    "user_info.registered": True
                }
            },
            {
                "$group": {
                    "_id": "$user_id",
                    "completed_targets": {"$sum": 1},
                    "username": {"$first": "$user_info.username"},
                    "first_name": {"$first": "$user_info.first_name"}
                }
            },
            {"$sort": {"completed_targets": DESCENDING}},
            {"$limit": 20}
        ]
        
        return list(self.targets.aggregate(pipeline))
    
    def get_user_stats(self, user_id: int, days: int = 30) -> Dict:
        """Get user statistics"""
        start_date = date.today() - timedelta(days=days)
        
        # Get targets in date range
        targets = list(self.targets.find({
            "user_id": user_id,
            "date": {"$gte": start_date}
        }))
        
        total_days = days
        completed = len([t for t in targets if t.get("status") == "completed"])
        pending = len([t for t in targets if t.get("status") == "pending"])
        dayoffs = len(list(self.dayoffs.find({
            "user_id": user_id,
            "date": {"$gte": start_date}
        })))
        
        active_days = total_days - dayoffs
        completion_rate = (completed / active_days * 100) if active_days > 0 else 0
        
        # Current streak
        today = date.today()
        streak = 0
        current_date = today
        
        while True:
            # Check if target exists and is completed
            target = self.targets.find_one({"user_id": user_id, "date": current_date})
            if target and target.get("status") == "completed":
                streak += 1
                current_date -= timedelta(days=1)
            else:
                # Check if day off
                if self.has_dayoff_today(user_id):
                    streak += 1
                    current_date -= timedelta(days=1)
                else:
                    break
        
        return {
            "completed_targets": completed,
            "pending_targets": pending,
            "dayoffs": dayoffs,
            "completion_rate": round(completion_rate, 1),
            "current_streak": streak,
            "active_days": active_days
        }
    
    # Admin Functions
    def get_all_users(self, group_id: int) -> List[Dict]:
        return list(self.users.find({"group_id": group_id}).sort("joined_at", DESCENDING))
    
    def get_group_settings(self, group_id: int) -> Dict:
        settings = self.settings.find_one({"group_id": group_id})
        if not settings:
            return {"daily_message_limit": config.Config.DEFAULT_DAILY_MESSAGE_LIMIT}
        return settings
    
    def close(self):
        self.client.close()
