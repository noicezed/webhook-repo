from flask import Blueprint, jsonify, request
from datetime import datetime, timezone

import logging

logging.basicConfig(level=logging.INFO)
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
        logging.error(f"Error formatting time: {e}")
        return "N/A"


@webhook.route("/receiver", methods=["POST"])
async def receiver():
    """
    Asynchronously handles GitHub webhook events for push and pull requests.
    """
    event = request.headers.get("X-GitHub-Event")
    payload = request.get_json()

    # Default to current UTC time if pushed_at is not available
    default_timestamp_iso = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    pushed_at_iso = payload.get("repository", {}).get("pushed_at")

    # If pushed_at is an integer timestamp, convert it to ISO format
    if isinstance(pushed_at_iso, int):
        pushed_at_iso = datetime.fromtimestamp(
            pushed_at_iso, tz=timezone.utc
        ).isoformat()
    elif not pushed_at_iso:  # if None or empty
        pushed_at_iso = default_timestamp_iso

    timestamp = format_time(pushed_at_iso)

    message = f"Received '{event}' event. "

    if event == "push":
        author = payload.get("pusher", {}).get("name", "N/A")
        branch = payload.get("ref", "N/A").split("/")[-1]
        # Accessing commits, ensuring it's a list and has at least one commit
        commits = payload.get("commits", [])
        commit_messages = []
        if commits:
            for commit in commits[:3]:  # Log first 3 commit messages
                commit_msg = commit.get("message", "N/A").split("\n")[
                    0
                ]  # Get first line of commit message
                commit_messages.append(commit_msg)

        commit_info = (
            "; ".join(commit_messages) if commit_messages else "No commit messages."
        )
        msg_details = f"Author: {author}, Branch: {branch}, Timestamp: {timestamp}. Commits: {commit_info}"
        print(f"Push event: {msg_details}")
        message += msg_details

    elif event == "pull_request":
        action = payload.get("action", "N/A")
        pr_data = payload.get("pull_request", {})
        author = pr_data.get("user", {}).get("login", "N/A")

        if action == "opened":
            from_branch = pr_data.get("head", {}).get("ref", "N/A")
            to_branch = pr_data.get("base", {}).get("ref", "N/A")
            created_at_iso = pr_data.get("created_at", default_timestamp_iso)
            created_at = format_time(created_at_iso)
            pr_title = pr_data.get("title", "N/A")
            msg_details = (
                f"Action: Opened by {author}. From: {from_branch} To: {to_branch}. "
                f"Title: '{pr_title}'. Timestamp: {created_at}"
            )
            print(f"Pull Request event: {msg_details}")
            message += msg_details

        elif action == "closed":
            merged = pr_data.get("merged", False)
            merged_at_iso = pr_data.get(
                "merged_at", default_timestamp_iso if merged else None
            )
            closed_at_iso = pr_data.get(
                "closed_at", default_timestamp_iso
            )  # always available for 'closed'

            if merged:
                merged_at = format_time(merged_at_iso)
                from_branch = pr_data.get("head", {}).get(
                    "ref", "N/A"
                )  # still available
                to_branch = pr_data.get("base", {}).get("ref", "N/A")  # still available
                pr_title = pr_data.get("title", "N/A")
                msg_details = (
                    f"Action: Merged by {author}. From: {from_branch} To: {to_branch}. "
                    f"Title: '{pr_title}'. Timestamp: {merged_at}"
                )
                print(f"Pull Request event: {msg_details}")
                message += msg_details
            else:
                closed_at = format_time(closed_at_iso)
                pr_title = pr_data.get("title", "N/A")
                msg_details = (
                    f"Action: Closed (not merged) by {author}. Title: '{pr_title}'. "
                    f"Timestamp: {closed_at}"
                )
                print(f"Pull Request event: {msg_details}")
                message += msg_details
        else:
            msg_details = f"Action: {action} by {author}."
            print(f"Pull Request event: {msg_details}")
            message += msg_details

    else:
        message += "No specific action taken."
        print(f"Unhandled event: {event}")

    return jsonify({"status": "received", "message": message}), 200
