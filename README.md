# 📡 GitHub Webhook Listener

This project listens to GitHub events (push, pull request, merge) and updates the frontend in real-time using Flask, MongoDB, WebSockets, and Docker Compose.

---

## 🧰 Tech Stack

* **Flask**: Handles incoming webhooks
* **MongoDB**: Stores event data
* **MongoDB Change Streams**: Detects new events instantly
* **WebSockets**: Pushes updates to the frontend in real-time
* **Docker Compose**: Orchestrates Flask, MongoDB, and ngrok
* **ngrok**: Exposes your local Flask server to the internet for GitHub webhooks

---

## ✨ Getting Started

### Prerequisites

* Docker & Docker Compose installed
* GitHub account

### Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/noicezed/webhook-repo.git
   cd webhook-repo
   ```

2. Start the services:

   ```bash
   docker-compose up
   ```

3. Once running, ngrok will provide a public URL. Use this URL to set up your GitHub webhook.

---

## 🔧 Setting Up GitHub Webhook

1. Go to your GitHub repository settings
2. Navigate to **Webhooks** and click **Add webhook**
3. Enter the ngrok URL followed by `/webhook/receiver` (e.g., `https://your-ngrok-url.ngrok.io/webhook/receiver`)
4. Set the content type to `application/json`
5. Choose events: push, pull request, and merge
6. Save the webhook

---

## 💻 Frontend

The frontend connects via WebSocket to receive real-time updates and displays them accordingly.

---

## 📂 Project Structure

* `main.py`: Flask app handling webhooks and WebSocket connections
* `index.html`: Frontend UI displaying events
* `docker-compose.yml`: Sets up Flask, MongoDB, and ngrok containers
* `requirements.txt`: Python dependencies

---

## 📝 Notes

* Using MongoDB's change streams allows real-time updates without polling
* Docker Compose simplifies the setup process
* ngrok makes local development and testing easier by exposing your Flask server to the internet

---

Feel free to fork this repo or suggest improvements!
