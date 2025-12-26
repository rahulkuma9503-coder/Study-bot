import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import PyMongoError, DuplicateKeyError
from bson import ObjectId

class MongoDB:
    def __init__(self, connection_string: str):
        self.client = MongoClient(connection_string)
        self.db = self.client.study_bot
        self.targets = self.db.targets
        self.users = self.db.users
        self.stats = self.db.stats
        self.registrations = self.db.registrations
        self.group_members = self.db.group_members
        self.daily_activity = self.db.daily_activity  # New collection for daily activity tracking
        
        # Drop problematic unique index if it exists
        self._cleanup_problematic_indexes()
        
        # Create correct indexes
        self._create_indexes()
    
    def _cleanup_problematic_indexes(self):
        """Remove any problematic indexes that might cause duplicate key errors"""
        try:
            # Get all indexes
            indexes = list(self.targets.index_information())
            
            # Look for problematic indexes
            for index_name in indexes:
                # Drop any unique index on user_id and date/deadline
                if index_name == 'user_id_1_date_-1' or index_name == 'user_id_1_deadline_-1':
                    try:
                        self.targets.drop_index(index_name)
                        print(f"✅ Dropped problematic index: {index_name}")
                    except Exception as e:
                        print(f"Note: Could not drop index {index_name}: {e}")
                
                # Drop any compound unique index that includes user_id
                elif '_1' in index_name and index_name != '_id_':
                    index_info = self.targets.index_information().get(index_name, {})
                    if index_info.get('unique'):
                        # Check if it includes user_id
                        key = index_info.get('key', [])
                        if any('user_id' in k for k in key):
                            try:
                                self.targets.drop_index(index_name)
                                print(f"✅ Dropped unique index: {index_name}")
                            except Exception as e:
                                print(f"Note: Could not drop index {index_name}: {e}")
        except Exception as e:
            print(f"Error cleaning up indexes: {e}")
    
    def _create_indexes(self):
        """Create necessary indexes"""
        # Create non-unique indexes for better query performance
        self.targets.create_index([("user_id", ASCENDING)])
        self.targets.create_index([("status", ASCENDING)])
        self.targets.create_index([("created_at", DESCENDING)])
        self.targets.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
        
        # Create indexes for registrations
        self.registrations.create_index([("user_id", ASCENDING)])
        self.registrations.create_index([("group_id", ASCENDING)])
        self.registrations.create_index([("user_id", ASCENDING), ("group_id", ASCENDING)])
        
        # Create indexes for group members
        self.group_members.create_index([("user_id", ASCENDING), ("group_id", ASCENDING)])
        
        # Create indexes for daily activity
        self.daily_activity.create_index([("user_id", ASCENDING)])
        self.daily_activity.create_index([("date", ASCENDING)])
        self.daily_activity.create_index([("user_id", ASCENDING), ("date", ASCENDING)])
    
    def add_target(self, target_data: Dict) -> str:
        """Add a new study target"""
        try:
            # Ensure target has a unique identifier for the user
            target_data["created_at"] = datetime.now()
            
            # Add a unique sequence number for this user
            last_target = self.targets.find_one(
                {"user_id": target_data["user_id"]},
                sort=[("sequence_number", DESCENDING)]
            )
            
            if last_target and "sequence_number" in last_target:
                target_data["sequence_number"] = last_target["sequence_number"] + 1
            else:
                target_data["sequence_number"] = 1
            
            result = self.targets.insert_one(target_data)
            
            # Update daily activity
            if result.inserted_id:
                today = datetime.now().date()
                self.update_daily_activity(target_data["user_id"], today, has_target=True)
            
            return str(result.inserted_id)
        except DuplicateKeyError as e:
            print(f"Duplicate key error: {e}")
            # Retry with a new sequence number
            target_data["sequence_number"] += 1
            result = self.targets.insert_one(target_data)
            return str(result.inserted_id)
        except Exception as e:
            print(f"Error adding target: {e}")
            return None
    
    def get_user_targets(self, user_id: int) -> List[Dict]:
        """Get all targets for a user"""
        try:
            targets = list(self.targets.find(
                {"user_id": user_id, "status": {"$ne": "deleted"}}
            ).sort("created_at", DESCENDING))
            return targets
        except Exception as e:
            print(f"Error getting user targets: {e}")
            return []
    
    def update_target_progress(self, target_id: str, progress: int) -> bool:
        """Update target progress percentage"""
        try:
            result = self.targets.update_one(
                {"_id": ObjectId(target_id)},
                {"$set": {"progress": progress, "updated_at": datetime.now()}}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error updating target progress: {e}")
            return False
    
    def update_target_deadline(self, target_id: str, deadline: datetime) -> bool:
        """Update target deadline"""
        try:
            result = self.targets.update_one(
                {"_id": ObjectId(target_id)},
                {"$set": {"deadline": deadline}}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error updating target deadline: {e}")
            return False
    
    def complete_target(self, target_id: str) -> bool:
        """Mark target as completed"""
        try:
            result = self.targets.update_one(
                {"_id": ObjectId(target_id)},
                {"$set": {
                    "status": "completed",
                    "progress": 100,
                    "completed_at": datetime.now()
                }}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error completing target: {e}")
            return False
    
    def get_user_stats(self, user_id: int) -> Dict:
        """Get user statistics"""
        try:
            targets = list(self.targets.find({"user_id": user_id}))
            
            total = len(targets)
            completed = len([t for t in targets if t.get("status") == "completed"])
            active = len([t for t in targets if t.get("status") == "active"])
            
            completion_rate = round((completed / total * 100) if total > 0 else 0, 1)
            
            # Calculate streak
            completed_dates = [
                t["completed_at"].date() 
                for t in targets 
                if t.get("completed_at") and t.get("status") == "completed"
            ]
            
            current_streak = self._calculate_streak(completed_dates)
            best_streak = self._calculate_best_streak(completed_dates)
            
            return {
                "total_targets": total,
                "completed_targets": completed,
                "active_targets": active,
                "completion_rate": completion_rate,
                "current_streak": current_streak,
                "best_streak": best_streak
            }
        except Exception as e:
            print(f"Error getting user stats: {e}")
            return {
                "total_targets": 0,
                "completed_targets": 0,
                "active_targets": 0,
                "completion_rate": 0,
                "current_streak": 0,
                "best_streak": 0
            }
    
    def _calculate_streak(self, dates: List) -> int:
        """Calculate current streak from completed dates"""
        if not dates:
            return 0
        
        dates = sorted(set(dates), reverse=True)
        today = datetime.now().date()
        streak = 0
        
        # Check if completed today
        if today in dates:
            streak += 1
        
        # Check consecutive days
        for i in range(1, len(dates)):
            if (dates[i-1] - dates[i]).days == 1:
                streak += 1
            else:
                break
        
        return streak
    
    def _calculate_best_streak(self, dates: List) -> int:
        """Calculate best streak from completed dates"""
        if not dates:
            return 0
        
        dates = sorted(set(dates))
        best_streak = 1
        current_streak = 1
        
        for i in range(1, len(dates)):
            if (dates[i] - dates[i-1]).days == 1:
                current_streak += 1
                best_streak = max(best_streak, current_streak)
            else:
                current_streak = 1
        
        return best_streak
    
    # Registration methods
    def add_registration(self, user_id: int, group_id: int, username: str) -> str:
        """Add a new registration request"""
        try:
            registration_data = {
                "user_id": user_id,
                "group_id": group_id,
                "username": username,
                "status": "pending",
                "created_at": datetime.now(),
                "accepted_at": None,
                "rules_accepted": False
            }
            result = self.registrations.insert_one(registration_data)
            return str(result.inserted_id)
        except Exception as e:
            print(f"Error adding registration: {e}")
            return None
    
    def update_registration_status(self, user_id: int, group_id: int, status: str) -> bool:
        """Update registration status"""
        try:
            update_data = {
                "status": status,
                "accepted_at": datetime.now() if status == "accepted" else None
            }
            result = self.registrations.update_one(
                {"user_id": user_id, "group_id": group_id},
                {"$set": update_data}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error updating registration status: {e}")
            return False
    
    def accept_rules(self, user_id: int, group_id: int) -> bool:
        """Mark rules as accepted"""
        try:
            result = self.registrations.update_one(
                {"user_id": user_id, "group_id": group_id},
                {"$set": {
                    "rules_accepted": True,
                    "status": "accepted",
                    "accepted_at": datetime.now()
                }}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error accepting rules: {e}")
            return False
    
    def get_registration_status(self, user_id: int, group_id: int) -> Optional[Dict]:
        """Get registration status for a user in a group"""
        try:
            return self.registrations.find_one({
                "user_id": user_id, 
                "group_id": group_id
            })
        except Exception as e:
            print(f"Error getting registration status: {e}")
            return None
    
    def is_user_registered(self, user_id: int, group_id: int) -> bool:
        """Check if user is registered and accepted"""
        registration = self.get_registration_status(user_id, group_id)
        return registration and registration.get("status") == "accepted"
    
    # Group member tracking methods
    def add_group_member(self, user_id: int, group_id: int, username: str):
        """Add or update group member"""
        try:
            self.group_members.update_one(
                {"user_id": user_id, "group_id": group_id},
                {"$set": {
                    "username": username,
                    "last_seen": datetime.now(),
                    "is_active": True
                }},
                upsert=True
            )
        except Exception as e:
            print(f"Error adding group member: {e}")
    
    def get_all_group_members(self, group_id: int) -> List[Dict]:
        """Get all members in a group"""
        try:
            return list(self.group_members.find({"group_id": group_id}))
        except Exception as e:
            print(f"Error getting group members: {e}")
            return []
    
    def check_and_register_existing_members(self, group_id: int, context) -> List[Dict]:
        """Check existing members and register those who aren't"""
        try:
            # Get all chat members
            chat_members = context.bot.get_chat_administrators(group_id)
            member_ids = [member.user.id for member in chat_members]
            
            unregistered_members = []
            for member_id in member_ids:
                if member_id == context.bot.id:
                    continue
                    
                if not self.is_user_registered(member_id, group_id):
                    # Add to registration database
                    registration = self.get_registration_status(member_id, group_id)
                    if not registration:
                        member_info = next((m for m in chat_members if m.user.id == member_id), None)
                        if member_info:
                            username = member_info.user.username or member_info.user.first_name
                            registration_id = self.add_registration(member_id, group_id, username)
                        else:
                            registration_id = None
                    else:
                        registration_id = str(registration.get("_id")) if registration.get("_id") else None
                    
                    unregistered_members.append({
                        "user_id": member_id,
                        "registration_id": registration_id
                    })
            
            return unregistered_members
        except Exception as e:
            print(f"Error checking existing members: {e}")
            return []
    
    # Daily activity tracking methods
    def update_daily_activity(self, user_id: int, date: datetime.date, has_target: bool = False):
        """Update daily activity for a user"""
        try:
            activity_data = {
                "user_id": user_id,
                "date": date,
                "has_target_today": has_target,
                "last_updated": datetime.now(),
                "notifications_sent": [],
                "marked_absent": False,
                "absent_reason": ""
            }
            
            self.daily_activity.update_one(
                {"user_id": user_id, "date": date},
                {"$set": activity_data},
                upsert=True
            )
        except Exception as e:
            print(f"Error updating daily activity: {e}")
    
    def get_users_without_target_today(self, date: datetime.date) -> List[Dict]:
        """Get all users who haven't set a target today"""
        try:
            # Get all registered users for the group
            registered_users = list(self.registrations.find(
                {"group_id": int(ALLOWED_GROUP_ID), "status": "accepted"}
            ))
            
            users_without_target = []
            for user in registered_users:
                user_id = user["user_id"]
                
                # Check if user has target today
                activity = self.daily_activity.find_one(
                    {"user_id": user_id, "date": date}
                )
                
                if not activity or not activity.get("has_target_today", False):
                    users_without_target.append({
                        "user_id": user_id,
                        "username": user.get("username", "Unknown"),
                        "notifications_sent": activity.get("notifications_sent", []) if activity else []
                    })
            
            return users_without_target
        except Exception as e:
            print(f"Error getting users without target: {e}")
            return []
    
    def record_notification_sent(self, user_id: int, date: datetime.date, notification_type: str):
        """Record that a notification was sent to a user"""
        try:
            self.daily_activity.update_one(
                {"user_id": user_id, "date": date},
                {
                    "$push": {"notifications_sent": {
                        "type": notification_type,
                        "sent_at": datetime.now()
                    }},
                    "$set": {"last_notification": datetime.now()}
                },
                upsert=True
            )
        except Exception as e:
            print(f"Error recording notification: {e}")
    
    def mark_user_absent(self, user_id: int, date: datetime.date, reason: str = "No target submitted"):
        """Mark user as absent for the day"""
        try:
            self.daily_activity.update_one(
                {"user_id": user_id, "date": date},
                {
                    "$set": {
                        "marked_absent": True,
                        "absent_reason": reason,
                        "absent_marked_at": datetime.now()
                    }
                },
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error marking user absent: {e}")
            return False
    
    def get_user_daily_status(self, user_id: int, date: datetime.date) -> Dict:
        """Get user's daily status"""
        try:
            activity = self.daily_activity.find_one({"user_id": user_id, "date": date})
            if activity:
                return {
                    "has_target": activity.get("has_target_today", False),
                    "notifications_sent": activity.get("notifications_sent", []),
                    "marked_absent": activity.get("marked_absent", False),
                    "absent_reason": activity.get("absent_reason", "")
                }
            else:
                return {
                    "has_target": False,
                    "notifications_sent": [],
                    "marked_absent": False,
                    "absent_reason": ""
                }
        except Exception as e:
            print(f"Error getting user daily status: {e}")
            return {
                "has_target": False,
                "notifications_sent": [],
                "marked_absent": False,
                "absent_reason": ""
            }
    
    def export_all_data(self) -> List[Dict]:
        """Export all data for backup"""
        try:
            return list(self.targets.find({}))
        except Exception as e:
            print(f"Error exporting data: {e}")
            return []
    
    def close(self):
        """Close database connection"""
        try:
            self.client.close()
        except Exception as e:
            print(f"Error closing database connection: {e}")
