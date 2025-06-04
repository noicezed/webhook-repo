# pylint: skip-file
import eventlet

eventlet.monkey_patch()
from flask import Flask
import logging
from bson import ObjectId
from app.webhook.routes import webhook
from app.extensions import init_mongo_service, get_mongo_service
from flask_socketio import SocketIO
from datetime import datetime
import pymongo.errors
import time

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

socketio = SocketIO(
    async_mode="eventlet",
    cors_allowed_origins="*",
    ping_timeout=120,       # Increased from 60
    ping_interval=30,       # Increased from 25
    logger=True,
    engineio_logger=True,
    max_http_buffer_size=1e8,
    async_handlers=False,
    manage_session=False,
    message_queue=None,
    allow_upgrades=True,    # Allow websocket upgrades
    compression=True,       # Enable compression
)


def serialize_change(doc):
    """
    Recursively serialize MongoDB documents to JSON-serializable format.
    Handles ObjectId, datetime, and nested structures.
    """
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_change(item) for item in doc]
    elif isinstance(doc, dict):
        return {k: serialize_change(v) for k, v in doc.items()}
    elif isinstance(doc, ObjectId):
        return str(doc)
    elif isinstance(doc, datetime):
        return doc.isoformat()
    return doc


def watch_mongodb_changes():
    """
    Optimized MongoDB change stream watcher for eventlet
    Only handles real-time changes - initial data sent per client in connect handler
    """
    logger.info("Starting MongoDB change stream watcher...")
    mongo_service = get_mongo_service()

    resume_token = None
    max_retries = 5
    retry_count = 0

    while True:
        try:
            pipeline = []
            watch_options = {
                "full_document": "updateLookup",
                "max_await_time_ms": 500,  # Reduced from 1000
            }
            if resume_token:
                watch_options["resume_after"] = resume_token

            with mongo_service.collection.watch(pipeline, **watch_options) as stream:
                logger.info("MongoDB change stream opened")
                retry_count = 0

                while True:
                    try:
                        # Non-blocking check for changes
                        change = stream.try_next()
                    except pymongo.errors.PyMongoError as e:
                        logger.error(f"MongoDB error in change stream: {e}")
                        break

                    if change is None:
                        # Yield control more frequently to prevent blocking
                        eventlet.sleep(0.1)  # Increased from 0.05
                        continue

                    # Process change
                    resume_token = change["_id"]
                    op = change["operationType"]
                    logger.info(f"MongoDB change detected: {op}")

                    if op == "insert":
                        doc = serialize_change(change["fullDocument"])
                        # Use emit directly instead of background task for simple operations
                        socketio.emit("git_action_new", doc)

                    # Yield control after processing each change
                    eventlet.sleep(0)

        except pymongo.errors.PyMongoError as e:
            logger.error(f"MongoDB connection error: {e}")
            retry_count += 1
            if retry_count >= max_retries:
                retry_count = 0
            sleep_time = min(30, 2**retry_count)
            logger.info(f"Retrying change stream in {sleep_time}s")
            eventlet.sleep(sleep_time)

        except Exception as e:
            logger.error(f"Unexpected error in watcher: {e}")
            eventlet.sleep(5)


def heartbeat():
    """Lightweight heartbeat that doesn't block"""
    while True:
        logger.debug("Heartbeat: socketio server still running")  # Changed to debug
        eventlet.sleep(30)  # Increased interval


def create_app():
    app = Flask(__name__)
    init_mongo_service(app)
    # check if the MongoDB service is initialized
    get_mongo_service()

    app.register_blueprint(webhook)

    # Initialize SocketIO with the app
    socketio.init_app(app)

    # Import and register SocketIO event handlers
    from app import socket_event

    # Start the background task
    socketio.start_background_task(watch_mongodb_changes)
    socketio.start_background_task(heartbeat)

    return app
