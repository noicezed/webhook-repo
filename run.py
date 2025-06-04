import eventlet

eventlet.monkey_patch()
from app import create_app, socketio

app = create_app()


if __name__ == "__main__":
    # Run with settings for persistent connections
    socketio.run(
        app,
        debug=False,  # Disable debug mode in production
        host="0.0.0.0",
        port=5000,
        use_reloader=False,  # Disable reloader in production
    )
