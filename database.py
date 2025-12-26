import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import PyMongoError
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
        
        # Create indexes
        self.targets.create_index([("user_id", ASCENDING)])
        self.targets.create_index([("status", ASCENDING)])
        self.targets.create_index([("created_at", DESCENDING)])
        self.registrations.create_index([("user_id", ASCENDING)])
        self.registrations.create_index([("group_id", ASCENDING)])
        self.group_members.create_index([("user_id", ASCENDING), ("group_id", ASCENDING)])
    
    def add_target(self, target_data: Dict) -> str:
        """Add a new study target"""
        try:
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
            
            # Calculate best streak
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
