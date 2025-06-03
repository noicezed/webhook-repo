from flask_socketio import emit, disconnect
from flask import request
from app import socketio
from app.extensions import get_mongo_service
from app import serialize_change
import logging
import time

logger = logging.getLogger(__name__)

# Track connected clients for debugging
connected_clients = set()


@socketio.on("connect")
def on_connect():
    """Handle client connection"""
    client_id = None
    try:
        client_id = request.sid
        logger.info(f"New client connecting with ID: {client_id}")

        # Add to connected clients set
        connected_clients.add(client_id)

        # Just confirm the socket is up — don’t hit Mongo here:
        emit(
            "connection_established",
            {"status": "connected", "clientId": client_id, "timestamp": time.time()},
        )

        logger.info(
            f"Client {client_id} connection established successfully. Total clients: {len(connected_clients)}"
        )
        return True

    except Exception as e:
        logger.error(
            f"Critical error in connect handler for client {client_id}: {e}",
            exc_info=True,
        )
        if client_id:
            connected_clients.discard(client_id)
        return False  # Reject the connection on error


@socketio.on("disconnect")
def on_disconnect():
    """Handle client disconnection"""
    client_id = None
    try:
        client_id = request.sid
        connected_clients.discard(client_id)
        logger.warning(
            f"Client {client_id} DISCONNECTED! Maybe because of backend crash?"
        )
    except Exception as e:
        logger.error(
            f"Error in disconnect handler for client {client_id}: {e}", exc_info=True
        )
