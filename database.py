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
        self.registrations = self.db.registrations  # New collection for registrations
        
        # Create indexes
        self.targets.create_index([("user_id", ASCENDING)])
        self.targets.create_index([("status", ASCENDING)])
        self.targets.create_index([("created_at", DESCENDING)])
        self.registrations.create_index([("user_id", ASCENDING)])
        self.registrations.create_index([("group_id", ASCENDING)])
    
    def add_target(self, target_data: Dict) -> str:
        """Add a new study target"""
        result = self.targets.insert_one(target_data)
        return str(result.inserted_id)
    
    def get_user_targets(self, user_id: int) -> List[Dict]:
        """Get all targets for a user"""
        return list(self.targets.find(
            {"user_id": user_id, "status": {"$ne": "deleted"}}
        ).sort("created_at", DESCENDING))
    
    def update_target_progress(self, target_id: str, progress: int) -> bool:
        """Update target progress percentage"""
        try:
            result = self.targets.update_one(
                {"_id": ObjectId(target_id)},
                {"$set": {"progress": progress, "updated_at": datetime.now()}}
            )
            return result.modified_count > 0
        except:
            return False
    
    def update_target_deadline(self, target_id: str, deadline: datetime) -> bool:
        """Update target deadline"""
        try:
            result = self.targets.update_one(
                {"_id": ObjectId(target_id)},
                {"$set": {"deadline": deadline}}
            )
            return result.modified_count > 0
        except:
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
        except:
            return False
    
    def get_user_stats(self, user_id: int) -> Dict:
        """Get user statistics"""
        targets = list(self.targets.find({"user_id": user_id}))
        
        total = len(targets)
        completed = len([t for t in targets if t.get("status") == "completed"])
        active = len([t for t in targets if t.get("status") == "active"])
        
        completion_rate = round((completed / total * 100) if total > 0 else 0, 1)
        
        # Calculate streak (simplified)
        completed_dates = [
            t["completed_at"].date() 
            for t in targets 
            if t.get("completed_at") and t.get("status") == "completed"
        ]
        
        current_streak = self._calculate_streak(completed_dates)
        
        return {
            "total_targets": total,
            "completed_targets": completed,
            "active_targets": active,
            "completion_rate": completion_rate,
            "current_streak": current_streak,
            "best_streak": 7  # Simplified, implement actual calculation
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
    
    # New registration methods
    def add_registration(self, user_id: int, group_id: int, username: str) -> str:
        """Add a new registration request"""
        registration_data = {
            "user_id": user_id,
            "group_id": group_id,
            "username": username,
            "status": "pending",  # pending, accepted, rejected
            "created_at": datetime.now(),
            "accepted_at": None,
            "rules_accepted": False
        }
        result = self.registrations.insert_one(registration_data)
        return str(result.inserted_id)
    
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
        except:
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
        except:
            return False
    
    def get_registration_status(self, user_id: int, group_id: int) -> Optional[Dict]:
        """Get registration status for a user in a group"""
        return self.registrations.find_one({
            "user_id": user_id, 
            "group_id": group_id
        })
    
    def is_user_registered(self, user_id: int, group_id: int) -> bool:
        """Check if user is registered and accepted"""
        registration = self.get_registration_status(user_id, group_id)
        return registration and registration.get("status") == "accepted"
    
    def export_all_data(self) -> List[Dict]:
        """Export all data for backup"""
        return list(self.targets.find({}))
    
    def close(self):
        """Close database connection"""
        self.client.close()
