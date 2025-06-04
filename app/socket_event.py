from flask_socketio import emit, disconnect
from flask import request
from app import socketio
from app.extensions import get_mongo_service
from app import serialize_change
import logging
import time
import traceback

logger = logging.getLogger(__name__)

# Track connected clients for debugging
connected_clients = {}


@socketio.on("connect")
def on_connect():
    """Handle client connection - optimized for fast response"""
    client_id = None
    try:
        client_id = request.sid
        client_info = {
            "connect_time": time.time(),
            "user_agent": request.headers.get("User-Agent", "Unknown"),
            "origin": request.headers.get("Origin", "Unknown"),
            "remote_addr": request.environ.get("REMOTE_ADDR", "Unknown"),
        }

        logger.info(f"New client connecting with ID: {client_id}")
        connected_clients[client_id] = client_info

        # Send immediate connection acknowledgment
        emit(
            "connection_established",
            {
                "status": "connected",
                "clientId": client_id,
                "timestamp": time.time(),
                "server_version": "1.0",
            },
        )

        # Send initial data in background to avoid blocking connection
        def send_initial_data():
            try:
                mongo_service = get_mongo_service()
                success, data, status_code = mongo_service.get_recent_git_actions(
                    limit=10
                )

                if success and data:
                    serialized_data = serialize_change(data)
                    logger.info(
                        f"Sending initial data to {client_id}: {len(serialized_data)} items"
                    )
                    socketio.emit(
                        "initial_data",
                        {
                            "actions": serialized_data,
                            "timestamp": time.time(),
                            "count": len(serialized_data),
                        },
                        room=client_id,  # Send only to this client
                    )
                else:
                    logger.warning(f"No initial data for {client_id}")
                    socketio.emit(
                        "initial_data",
                        {
                            "actions": [],
                            "timestamp": time.time(),
                            "count": 0,
                            "message": "No data available",
                        },
                        room=client_id,
                    )
            except Exception as data_error:
                logger.error(
                    f"Error fetching initial data for {client_id}: {data_error}"
                )
                socketio.emit(
                    "initial_data",
                    {
                        "actions": [],
                        "timestamp": time.time(),
                        "count": 0,
                        "error": "Data fetch failed",
                    },
                    room=client_id,
                )

        # Run initial data fetch in background
        socketio.start_background_task(send_initial_data)

        logger.info(
            f"Client {client_id} setup complete. Total clients: {len(connected_clients)}"
        )
        return True

    except Exception as e:
        logger.error(f"Critical error in connect handler for client {client_id}: {e}")
        if client_id and client_id in connected_clients:
            del connected_clients[client_id]
        return False


@socketio.on("disconnect")
def on_disconnect(reason=None):
    """Handle client disconnection"""
    client_id = None
    try:
        client_id = request.sid

        # Get connection info if available
        connection_info = connected_clients.get(client_id, {})
        connect_time = connection_info.get("connect_time", time.time())
        connection_duration = time.time() - connect_time

        # Remove from tracking
        if client_id in connected_clients:
            del connected_clients[client_id]

        logger.warning(
            f"Client {client_id} DISCONNECTED after {connection_duration:.2f} seconds! "
            f"Reason: {reason}. Remaining clients: {len(connected_clients)}"
        )

        # Log additional disconnect context
        if connection_duration < 5:
            logger.error(
                f"VERY SHORT CONNECTION ({connection_duration:.2f}s) - possible client-side issue"
            )

        # Log different disconnect reasons
        if reason:
            if reason == "transport error":
                logger.error(
                    f"Transport error for {client_id} - network/connection issue"
                )
            elif reason == "client namespace disconnect":
                logger.info(f"Client {client_id} initiated disconnect")
            elif reason == "server namespace disconnect":
                logger.info(f"Server initiated disconnect for {client_id}")
            elif reason == "ping timeout":
                logger.error(f"Ping timeout for {client_id} - connection lost")

    except Exception as e:
        logger.error(f"Error in disconnect handler for client {client_id}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")


@socketio.on("error")
def handle_error(e):
    """Handle socket errors"""
    client_id = getattr(request, "sid", "unknown")
    logger.error(f"Socket error from client {client_id}: {e}")
    logger.error(f"Error traceback: {traceback.format_exc()}")


@socketio.on("request_initial_data")
def handle_initial_data_request():
    """Handle explicit request for initial data"""
    client_id = getattr(request, "sid", "unknown")
    logger.info(f"Client {client_id} explicitly requested initial data")

    try:
        mongo_service = get_mongo_service()
        success, data, status_code = mongo_service.get_recent_git_actions(limit=20)

        if success and data:
            serialized_data = serialize_change(data)
            logger.info(
                f"Sending requested data to {client_id}: {len(serialized_data)} items"
            )
            emit(
                "initial_data",
                {
                    "actions": serialized_data,
                    "timestamp": time.time(),
                    "count": len(serialized_data),
                    "requested": True,
                },
            )
        else:
            logger.warning(f"No data available for explicit request from {client_id}")
            emit(
                "initial_data",
                {
                    "actions": [],
                    "error": "No data available",
                    "status_code": status_code,
                    "timestamp": time.time(),
                    "count": 0,
                    "requested": True,
                },
            )

    except Exception as e:
        logger.error(f"Error handling data request from {client_id}: {e}")
        emit(
            "initial_data",
            {
                "actions": [],
                "error": "Server error",
                "timestamp": time.time(),
                "count": 0,
                "requested": True,
            },
        )


@socketio.on("ping")
def handle_ping():
    """Handle client ping"""
    client_id = getattr(request, "sid", "unknown")
    logger.debug(f"Ping from {client_id}")
    emit("pong", {"timestamp": time.time()})


@socketio.on("heartbeat")
def handle_heartbeat():
    """Handle client heartbeat"""
    client_id = getattr(request, "sid", "unknown")
    logger.debug(f"Heartbeat from {client_id}")
    emit("heartbeat_ack", {"timestamp": time.time()})


@socketio.on("get_status")
def handle_status():
    """Handle status request"""
    client_id = getattr(request, "sid", "unknown")
    emit(
        "status_response",
        {
            "connected_clients": len(connected_clients),
            "client_id": client_id,
            "timestamp": time.time(),
        },
    )


# Add this error handler to catch all unhandled events
@socketio.on_error_default
def default_error_handler(e):
    client_id = getattr(request, "sid", "unknown")
    logger.error(f"Unhandled socket error from {client_id}: {e}")
    logger.error(f"Error details: {traceback.format_exc()}")


# Utility function for safe broadcasting
def safe_broadcast(event_name, data, room=None):
    """Safely broadcast events with error handling"""
    try:
        if not connected_clients:
            logger.debug(f"No clients connected for broadcast: {event_name}")
            return False

        logger.info(f"Broadcasting {event_name} to {len(connected_clients)} clients")
        if room:
            socketio.emit(event_name, data, room=room)
        else:
            socketio.emit(event_name, data)
        return True

    except Exception as e:
        logger.error(f"Error broadcasting {event_name}: {e}")
        logger.error(f"Broadcast error traceback: {traceback.format_exc()}")
        return False


# Add periodic connection health check
def log_connection_stats():
    """Log current connection statistics"""
    if connected_clients:
        current_time = time.time()
        logger.info(f"Active connections: {len(connected_clients)}")

        for client_id, info in connected_clients.items():
            duration = current_time - info["connect_time"]
            logger.info(f"  {client_id}: connected for {duration:.1f}s")
    else:
        logger.info("No active connections")
