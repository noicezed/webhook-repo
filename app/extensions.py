from flask_pymongo import PyMongo
from bson import ObjectId
from datetime import datetime, timezone
import logging
import os
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize PyMongo
mongo = PyMongo()
# Global service instance
mongo_service = None

class GitAction(Enum):
    PUSH = "PUSH"
    PULL_REQUEST = "PULL_REQUEST"
    MERGE = "MERGE"


class MongoService:
    """Service class for MongoDB operations related to Git actions"""

    def __init__(self, mongo_instance):
        self.mongo = mongo_instance
        self.collection = self.mongo.db.git_actions

    def create_git_action(self, action_data):
        """
        Create a new git action record in MongoDB

        Args:
            action_data (dict): Dictionary containing git action data

        Returns:
            tuple: (success: bool, result: dict/str, status_code: int)
        """
        try:
            # Validate required fields
            required_fields = [
                "request_id",
                "author",
                "action",
                "from_branch",
                "to_branch",
                "timestamp",
            ]
            for field in required_fields:
                if field not in action_data or action_data[field] is None:
                    logger.error(f"Missing required field: {field}")
                    return False, f"Missing required field: {field}", 400

            # Validate action enum
            if action_data["action"] not in [action.value for action in GitAction]:
                logger.error(f"Invalid action: {action_data['action']}")
                return (
                    False,
                    "Invalid action. Must be one of: PUSH, PULL_REQUEST, MERGE",
                    400,
                )

            # Ensure timestamp is datetime object
            if isinstance(action_data["timestamp"], str):
                try:
                    action_data["timestamp"] = datetime.fromisoformat(
                        action_data["timestamp"]
                    )
                except ValueError as e:
                    logger.error(f"Invalid timestamp format: {e}")
                    return False, "Invalid timestamp format", 400

            # Insert document
            result = self.collection.insert_one(action_data)

            # Get the inserted document
            inserted_doc = self.collection.find_one({"_id": result.inserted_id})

            # Convert ObjectId to string for JSON serialization
            inserted_doc["_id"] = str(inserted_doc["_id"])

            logger.info(
                f"Successfully created git action with ID: {inserted_doc['_id']}"
            )
            return True, inserted_doc, 201

        except Exception as e:
            logger.error(f"Error creating git action: {str(e)}")
            return False, f"Database error: {str(e)}", 500

    def get_git_action(self, action_id):
        """
        Retrieve a git action by ID

        Args:
            action_id (str): MongoDB ObjectId as string

        Returns:
            tuple: (success: bool, result: dict/str, status_code: int)
        """
        try:
            if not ObjectId.is_valid(action_id):
                return False, "Invalid action ID format", 400

            action = self.collection.find_one({"_id": ObjectId(action_id)})

            if not action:
                return False, "Git action not found", 404

            # Convert ObjectId to string
            action["_id"] = str(action["_id"])

            return True, action, 200

        except Exception as e:
            logger.error(f"Error retrieving git action: {str(e)}")
            return False, f"Database error: {str(e)}", 500

    def get_git_actions_by_author(self, author, page=1, limit=10):
        """
        Retrieve git actions by author with pagination

        Args:
            author (str): Author name
            page (int): Page number (default: 1)
            limit (int): Number of records per page (default: 10)

        Returns:
            tuple: (success: bool, result: dict/str, status_code: int)
        """
        try:
            skip = (page - 1) * limit

            # Query for actions by author
            actions = list(
                self.collection.find({"author": author})
                .skip(skip)
                .limit(limit)
                .sort("timestamp", -1)
            )

            # Convert ObjectIds to strings
            for action in actions:
                action["_id"] = str(action["_id"])

            # Get total count
            total_count = self.collection.count_documents({"author": author})

            result = {
                "actions": actions,
                "total": total_count,
                "page": page,
                "limit": limit,
                "total_pages": (total_count + limit - 1) // limit,
            }

            return True, result, 200

        except Exception as e:
            logger.error(f"Error retrieving git actions by author: {str(e)}")
            return False, f"Database error: {str(e)}", 500

    def get_git_actions_by_branch(self, branch_name, page=1, limit=10):
        """
        Retrieve git actions involving a specific branch

        Args:
            branch_name (str): Branch name
            page (int): Page number (default: 1)
            limit (int): Number of records per page (default: 10)

        Returns:
            tuple: (success: bool, result: dict/str, status_code: int)
        """
        try:
            skip = (page - 1) * limit

            # Query for actions involving the branch (either from or to)
            query = {"$or": [{"from_branch": branch_name}, {"to_branch": branch_name}]}

            actions = list(
                self.collection.find(query)
                .skip(skip)
                .limit(limit)
                .sort("timestamp", -1)
            )

            # Convert ObjectIds to strings
            for action in actions:
                action["_id"] = str(action["_id"])

            # Get total count
            total_count = self.collection.count_documents(query)

            result = {
                "actions": actions,
                "total": total_count,
                "page": page,
                "limit": limit,
                "total_pages": (total_count + limit - 1) // limit,
            }

            return True, result, 200

        except Exception as e:
            logger.error(f"Error retrieving git actions by branch: {str(e)}")
            return False, f"Database error: {str(e)}", 500

    def get_recent_git_actions(self, limit=20):
        """
        Retrieve recent git actions

        Args:
            limit (int): Number of recent actions to retrieve (default: 20)

        Returns:
            tuple: (success: bool, result: dict/str, status_code: int)
        """
        try:
            actions = list(self.collection.find().sort("timestamp", -1).limit(limit))

            # Convert ObjectIds to strings
            for action in actions:
                action["_id"] = str(action["_id"])

            return True, actions, 200

        except Exception as e:
            logger.error(f"Error retrieving recent git actions: {str(e)}")
            return False, f"Database error: {str(e)}", 500

    def delete_git_action(self, action_id):
        """
        Delete a git action by ID

        Args:
            action_id (str): MongoDB ObjectId as string

        Returns:
            tuple: (success: bool, result: str, status_code: int)
        """
        try:
            if not ObjectId.is_valid(action_id):
                return False, "Invalid action ID format", 400

            result = self.collection.delete_one({"_id": ObjectId(action_id)})

            if result.deleted_count == 0:
                return False, "Git action not found", 404

            logger.info(f"Successfully deleted git action with ID: {action_id}")
            return True, "Git action deleted successfully", 200

        except Exception as e:
            logger.error(f"Error deleting git action: {str(e)}")
            return False, f"Database error: {str(e)}", 500

    def update_git_action(self, action_id, update_data):
        """
        Update a git action by ID

        Args:
            action_id (str): MongoDB ObjectId as string
            update_data (dict): Data to update

        Returns:
            tuple: (success: bool, result: dict/str, status_code: int)
        """
        try:
            if not ObjectId.is_valid(action_id):
                return False, "Invalid action ID format", 400

            # Validate action enum if provided
            if "action" in update_data and update_data["action"] not in [
                action.value for action in GitAction
            ]:
                return (
                    False,
                    "Invalid action. Must be one of: PUSH, PULL_REQUEST, MERGE",
                    400,
                )

            # Ensure timestamp is datetime object if provided
            if "timestamp" in update_data and isinstance(update_data["timestamp"], str):
                try:
                    update_data["timestamp"] = datetime.fromisoformat(
                        update_data["timestamp"]
                    )
                except ValueError:
                    return False, "Invalid timestamp format", 400

            result = self.collection.update_one(
                {"_id": ObjectId(action_id)}, {"$set": update_data}
            )

            if result.matched_count == 0:
                return False, "Git action not found", 404

            # Get updated document
            updated_doc = self.collection.find_one({"_id": ObjectId(action_id)})
            updated_doc["_id"] = str(updated_doc["_id"])

            logger.info(f"Successfully updated git action with ID: {action_id}")
            return True, updated_doc, 200

        except Exception as e:
            logger.error(f"Error updating git action: {str(e)}")
            return False, f"Database error: {str(e)}", 500

    def watch_git_actions(self):
        """
        Watch for real-time changes in git_actions collection.
        Yields change documents.
        """
        try:
            with self.collection.watch() as change_stream:
                for change in change_stream:
                    # You can filter or transform changes here if needed
                    yield change
        except Exception as e:
            logger.error(f"Error watching git actions: {str(e)}")
            return False, f"Error watching git actions: {str(e)}", 500
            # You can raise or handle reconnect here

    def stream_git_actions(self, limit=20):
        """
        Yield initial data from DB, then continue yielding new changes in real-time.
        """
        try:
            # 1. Yield initial recent data
            initial_data = self.collection.find().sort("timestamp", -1).limit(limit)
            for doc in initial_data:
                doc["_id"] = str(doc["_id"])
                yield doc

            # 2. Start watching for new changes
            with self.collection.watch() as change_stream:
                for change in change_stream:
                    if change["operationType"] == "insert":
                        doc = change["fullDocument"]
                        doc["_id"] = str(doc["_id"])
                        yield doc
        except Exception as e:
            logger.error(f"Error in stream_git_actions: {str(e)}")
            yield {"error": str(e)}


def init_mongo_service(app):
    """
    Initialize MongoDB service with Flask app

    Args:
        app: Flask application instance
    """
    global mongo_service

    # # Set MongoDB URI from environment or use default
    app.config["MONGO_URI"] = os.getenv(
        "MONGO_URI", "mongodb://localhost:27017/git_actions_db"
    )

    # Initialize PyMongo with app
    mongo.init_app(app)

    # Create service instance
    mongo_service = MongoService(mongo)

    logger.info("MongoDB service initialized successfully")

    return mongo_service


def get_mongo_service():
    """
    Get the global MongoDB service instance

    Returns:
        MongoService: MongoDB service instance
    """
    if mongo_service is None:
        raise RuntimeError(
            "MongoDB service not initialized. Call init_mongo_service() first."
        )

    return mongo_service
