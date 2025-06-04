from flask import Blueprint, jsonify, request
from datetime import datetime, timezone
import logging
import hashlib

# Import our MongoDB extension
from app.extensions import get_mongo_service, GitAction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

webhook = Blueprint("Webhook", __name__, url_prefix="/webhook")


@webhook.route("/", methods=["GET"])
def index():
    """
    Returns a simple message indicating the webhook is active.
    """
    return jsonify({"message": "Webhook is active"}), 200


def format_time(iso_time_str):
    """Converts an ISO 8601 timestamp string to 'YYYY-MM-DD HH:MM:SS' format."""
    try:
        if iso_time_str:
            # Ensure the timestamp has timezone information, defaulting to UTC if 'Z' is present or missing.
            if iso_time_str.endswith("Z"):
                dt = datetime.fromisoformat(iso_time_str.replace("Z", "+00:00"))
            else:
                # Attempt to parse directly, assuming it might already have timezone or be naive UTC
                try:
                    dt = datetime.fromisoformat(iso_time_str)
                except (
                    ValueError
                ):  # Handle cases where timezone might be missing for fromisoformat
                    dt = datetime.fromisoformat(
                        iso_time_str + "+00:00"
                    )  # Assume UTC if error

            # If datetime object is naive, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S %Z")  # Added %Z for timezone
        return "N/A"
    except Exception as e:
        logger.error(f"Error formatting time: {e}")
        return "N/A"


def parse_timestamp_to_datetime(iso_time_str):
    """Convert ISO timestamp string to datetime object for MongoDB storage."""
    try:
        if iso_time_str:
            if iso_time_str.endswith("Z"):
                dt = datetime.fromisoformat(iso_time_str.replace("Z", "+00:00"))
            else:
                try:
                    dt = datetime.fromisoformat(iso_time_str)
                except ValueError:
                    dt = datetime.fromisoformat(iso_time_str + "+00:00")

            # If datetime object is naive, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        return datetime.utcnow().replace(tzinfo=timezone.utc)
    except Exception as e:
        logger.error(f"Error parsing timestamp: {e}")
        return datetime.utcnow().replace(tzinfo=timezone.utc)


def generate_request_id(event_type, payload):
    """Generate a unique request ID based on event type and payload."""
    try:
        if event_type == "push":
            # Use the after commit SHA for push events
            after_sha = payload.get("after", "")
            if after_sha:
                return after_sha

            # Fallback: use first commit SHA if available
            commits = payload.get("commits", [])
            if commits:
                return commits[0].get("id", "")

        elif event_type == "pull_request":
            # Use PR number for pull request events
            pr_data = payload.get("pull_request", {})
            pr_number = pr_data.get("number")
            if pr_number:
                return f"pr-{pr_number}"

        # Fallback: generate hash from timestamp and event type
        timestamp = str(datetime.utcnow().timestamp())
        return hashlib.md5(f"{event_type}-{timestamp}".encode()).hexdigest()[:12]

    except Exception as e:
        logger.error(f"Error generating request ID: {e}")
        return hashlib.md5(
            f"{event_type}-{datetime.utcnow().timestamp()}".encode()
        ).hexdigest()[:12]


@webhook.route("/receiver", methods=["POST"])
def receiver():
    """
    Handles GitHub webhook events for push and pull requests and stores them in MongoDB.
    """
    event = request.headers.get("X-GitHub-Event")
    payload = request.get_json()

    if not payload:
        logger.error("No payload received")
        return jsonify({"status": "error", "message": "No payload received"}), 400

    # Get MongoDB service
    try:
        mongo_service = get_mongo_service()
    except RuntimeError as e:
        logger.error(f"MongoDB service error: {e}")
        return jsonify(
            {"status": "error", "message": "Database service unavailable"}
        ), 500

    # Default to current UTC time if timestamp is not available
    default_timestamp = datetime.utcnow().replace(tzinfo=timezone.utc)

    # Generate request ID
    request_id = generate_request_id(event, payload)

    message = f"Received '{event}' event. "
    git_action_data = None

    if event == "push":
        try:
            author = payload.get("pusher", {}).get("name", "Unknown")
            branch = (
                payload.get("ref", "").split("/")[-1]
                if payload.get("ref")
                else "unknown"
            )

            # Get timestamp from repository pushed_at or use default
            pushed_at_iso = payload.get("repository", {}).get("pushed_at")
            if isinstance(pushed_at_iso, int):
                pushed_at_iso = datetime.fromtimestamp(
                    pushed_at_iso, tz=timezone.utc
                ).isoformat()

            timestamp = (
                parse_timestamp_to_datetime(pushed_at_iso)
                if pushed_at_iso
                else default_timestamp
            )

            # Get commit information
            commits = payload.get("commits", [])
            commit_messages = []
            if commits:
                for commit in commits[:3]:  # Log first 3 commit messages
                    commit_msg = commit.get("message", "N/A").split("\n")[0]
                    commit_messages.append(commit_msg)

            commit_info = (
                "; ".join(commit_messages) if commit_messages else "No commit messages."
            )

            # Prepare git action data for MongoDB
            git_action_data = {
                "request_id": request_id,
                "author": author,
                "action": GitAction.PUSH.value,
                "from_branch": branch,  # For push, from and to branch are the same
                "to_branch": branch,
                "timestamp": timestamp,
                "metadata": {
                    "commit_count": len(commits),
                    "commit_messages": commit_messages,
                    "repository": payload.get("repository", {}).get(
                        "full_name", "Unknown"
                    ),
                },
            }

            # Store in MongoDB
            success, result, status_code = mongo_service.create_git_action(
                git_action_data
            )

            if success:
                logger.info(f"Successfully stored push event with ID: {result['_id']}")
                msg_details = f"Author: {author}, Branch: {branch}, Timestamp: {format_time(timestamp.isoformat())}. Commits: {commit_info}"
            else:
                logger.error(f"Failed to store push event: {result}")
                msg_details = f"Author: {author}, Branch: {branch}, Timestamp: {format_time(timestamp.isoformat())}. Commits: {commit_info} [DB Error: {result}]"

            print(f"Push event: {msg_details}")
            message += msg_details

        except Exception as e:
            logger.error(f"Error processing push event: {e}")
            message += f"Error processing push event: {str(e)}"

    elif event == "pull_request":
        try:
            action = payload.get("action", "N/A")
            pr_data = payload.get("pull_request", {})
            author = pr_data.get("user", {}).get("login", "Unknown")

            if action == "opened":
                from_branch = pr_data.get("head", {}).get("ref", "unknown")
                to_branch = pr_data.get("base", {}).get("ref", "unknown")
                created_at_iso = pr_data.get("created_at")
                timestamp = (
                    parse_timestamp_to_datetime(created_at_iso)
                    if created_at_iso
                    else default_timestamp
                )
                pr_title = pr_data.get("title", "N/A")
                pr_number = pr_data.get("number")

                # Prepare git action data for MongoDB
                git_action_data = {
                    "request_id": request_id,
                    "author": author,
                    "action": GitAction.PULL_REQUEST.value,
                    "from_branch": from_branch,
                    "to_branch": to_branch,
                    "timestamp": timestamp,
                    "metadata": {
                        "pr_action": "opened",
                        "pr_number": pr_number,
                        "pr_title": pr_title,
                        "repository": payload.get("repository", {}).get(
                            "full_name", "Unknown"
                        ),
                    },
                }

                # Store in MongoDB
                success, result, status_code = mongo_service.create_git_action(
                    git_action_data
                )

                if success:
                    logger.info(
                        f"Successfully stored PR opened event with ID: {result['_id']}"
                    )

                msg_details = (
                    f"Action: Opened by {author}. From: {from_branch} To: {to_branch}. "
                    f"Title: '{pr_title}'. Timestamp: {format_time(timestamp.isoformat())}"
                )
                print(f"Pull Request event: {msg_details}")
                message += msg_details

            elif action == "closed":
                merged = pr_data.get("merged", False)
                from_branch = pr_data.get("head", {}).get("ref", "unknown")
                to_branch = pr_data.get("base", {}).get("ref", "unknown")
                pr_title = pr_data.get("title", "N/A")
                pr_number = pr_data.get("number")

                if merged:
                    merged_at_iso = pr_data.get("merged_at")
                    timestamp = (
                        parse_timestamp_to_datetime(merged_at_iso)
                        if merged_at_iso
                        else default_timestamp
                    )

                    # Prepare git action data for MongoDB (MERGE action)
                    git_action_data = {
                        "request_id": request_id,
                        "author": author,
                        "action": GitAction.MERGE.value,
                        "from_branch": from_branch,
                        "to_branch": to_branch,
                        "timestamp": timestamp,
                        "metadata": {
                            "pr_action": "merged",
                            "pr_number": pr_number,
                            "pr_title": pr_title,
                            "repository": payload.get("repository", {}).get(
                                "full_name", "Unknown"
                            ),
                        },
                    }

                    # Store in MongoDB
                    success, result, status_code = mongo_service.create_git_action(
                        git_action_data
                    )

                    if success:
                        logger.info(
                            f"Successfully stored PR merged event with ID: {result['_id']}"
                        )

                    msg_details = (
                        f"Action: Merged by {author}. From: {from_branch} To: {to_branch}. "
                        f"Title: '{pr_title}'. Timestamp: {format_time(timestamp.isoformat())}"
                    )
                else:
                    closed_at_iso = pr_data.get("closed_at")
                    timestamp = (
                        parse_timestamp_to_datetime(closed_at_iso)
                        if closed_at_iso
                        else default_timestamp
                    )

                    # For closed (not merged) PRs, we still store as PULL_REQUEST with metadata
                    git_action_data = {
                        "request_id": request_id,
                        "author": author,
                        "action": GitAction.PULL_REQUEST.value,
                        "from_branch": from_branch,
                        "to_branch": to_branch,
                        "timestamp": timestamp,
                        "metadata": {
                            "pr_action": "closed",
                            "pr_number": pr_number,
                            "pr_title": pr_title,
                            "merged": False,
                            "repository": payload.get("repository", {}).get(
                                "full_name", "Unknown"
                            ),
                        },
                    }

                    # Store in MongoDB
                    success, result, status_code = mongo_service.create_git_action(
                        git_action_data
                    )

                    if success:
                        logger.info(
                            f"Successfully stored PR closed event with ID: {result['_id']}"
                        )

                    msg_details = (
                        f"Action: Closed (not merged) by {author}. Title: '{pr_title}'. "
                        f"Timestamp: {format_time(timestamp.isoformat())}"
                    )

                print(f"Pull Request event: {msg_details}")
                message += msg_details
            else:
                msg_details = f"Action: {action} by {author}."
                print(f"Pull Request event: {msg_details}")
                message += msg_details

        except Exception as e:
            logger.error(f"Error processing pull request event: {e}")
            message += f"Error processing pull request event: {str(e)}"

    else:
        message += "No specific action taken."
        print(f"Unhandled event: {event}")

    return jsonify({"status": "received", "message": message}), 200


# Additional API endpoints for querying stored data
@webhook.route("/actions", methods=["GET"])
def get_actions():
    """Get all git actions with pagination"""
    try:
        mongo_service = get_mongo_service()
        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 10, type=int)

        # For simplicity, we'll get recent actions
        success, result, status_code = mongo_service.get_recent_git_actions(
            limit * page
        )

        if success:
            # Apply pagination manually since we're using get_recent_git_actions
            start_idx = (page - 1) * limit
            end_idx = start_idx + limit
            paginated_actions = result[start_idx:end_idx]

            return jsonify(
                {
                    "actions": paginated_actions,
                    "total": len(result),
                    "page": page,
                    "limit": limit,
                }
            ), 200
        else:
            return jsonify({"error": result}), status_code

    except Exception as e:
        logger.error(f"Error getting actions: {e}")
        return jsonify({"error": str(e)}), 500


@webhook.route("/actions/author/<author_name>", methods=["GET"])
def get_actions_by_author(author_name):
    """Get actions by specific author"""
    try:
        mongo_service = get_mongo_service()
        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 10, type=int)

        success, result, status_code = mongo_service.get_git_actions_by_author(
            author_name, page, limit
        )

        if success:
            return jsonify(result), 200
        else:
            return jsonify({"error": result}), status_code

    except Exception as e:
        logger.error(f"Error getting actions by author: {e}")
        return jsonify({"error": str(e)}), 500


@webhook.route("/actions/branch/<branch_name>", methods=["GET"])
def get_actions_by_branch(branch_name):
    """Get actions by specific branch"""
    try:
        mongo_service = get_mongo_service()
        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 10, type=int)

        success, result, status_code = mongo_service.get_git_actions_by_branch(
            branch_name, page, limit
        )

        if success:
            return jsonify(result), 200
        else:
            return jsonify({"error": result}), status_code

    except Exception as e:
        logger.error(f"Error getting actions by branch: {e}")
        return jsonify({"error": str(e)}), 500


@webhook.route("/actions/<action_id>", methods=["GET"])
def get_action(action_id):
    """Get specific action by ID"""
    try:
        mongo_service = get_mongo_service()
        success, result, status_code = mongo_service.get_git_action(action_id)

        if success:
            return jsonify(result), 200
        else:
            return jsonify({"error": result}), status_code

    except Exception as e:
        logger.error(f"Error getting action: {e}")
        return jsonify({"error": str(e)}), 500
