---
name: chatgpt-pro-api
description: ChatGPT Pro API service via Chrome automation. Use when user needs ChatGPT Pro deep analysis capabilities, research-grade AI responses, or wants to integrate ChatGPT Pro into automation workflows.
---

# ChatGPT Pro API Service

Owner: barz

## Connection Info

| Item | Value |
|----|----|
| **Dashboard** | `https://chatgpt-pro-api.gpu5090.whaleforce.dev` |
| **API Base URL** | `https://chatgpt-pro-api.gpu5090.whaleforce.dev` |
| **Internal IP** | `172.23.22.100:8600` |

## Quick Start

```bash
# Submit task
curl -X POST "https://chatgpt-pro-api.gpu5090.whaleforce.dev/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Analyze investment value differences between AAPL and TSLA"
  }'

# Response: {"success":true,"task_id":"a1b2","status":"queued",...}

# Query result (wait up to 60 seconds)
curl "https://chatgpt-pro-api.gpu5090.whaleforce.dev/task/a1b2?wait=60"
```

## Python Example

```python
import requests

API_URL = "https://chatgpt-pro-api.gpu5090.whaleforce.dev"

# Submit task
response = requests.post(f"{API_URL}/chat", json={
    "prompt": "Design a stock selection strategy combining technical and fundamental analysis"
})
task_id = response.json()["task_id"]
print(f"Task ID: {task_id}")

# Wait for result (using wait parameter)
result = requests.get(f"{API_URL}/task/{task_id}?wait=60").json()

if result["status"] == "completed":
    print(result["answer"])
else:
    print(f"Status: {result['status']}, Progress: {result['progress']}")
```

## API Endpoints

| Endpoint | Method | Description |
|----|----|----|
| `/` | GET | Dashboard |
| `/health` | GET | Health check |
| `/chat` | POST | Submit new task |
| `/task/{task_id}` | GET | Query task status |
| `/task/{task_id}` | DELETE | Cancel task (queued only) |
| `/tasks` | GET | List all tasks |
| `/task/{task_id}/screenshots` | GET | List task screenshots |
| `/screenshots/{filename}` | GET | Get screenshot file |

## Request/Response Format

### POST /chat

Request:

```json
{
  "prompt": "Your question"
}
```

Response:

```json
{
  "success": true,
  "task_id": "a1b2",
  "status": "queued",
  "prompt_with_id": "[a1b2] Your question",
  "created_at": "2026-01-01T10:00:00.000000"
}
```

### GET /task/{task_id}

Query Parameters:

* `wait` (optional): Wait seconds, max 60

Response (completed):

```json
{
  "success": true,
  "task_id": "a1b2",
  "status": "completed",
  "prompt": "Your question",
  "answer": "ChatGPT Pro response content",
  "error": null,
  "progress": "Done",
  "wait_time": 45
}
```

### GET /health

```json
{
  "status": "ok",
  "mode": "parallel",
  "driver_ready": true,
  "sender_running": true,
  "checker_running": true,
  "queued": 0,
  "sent": 1,
  "processing": 0,
  "completed": 5
}
```

## Task Status

| Status | Description |
|----|----|
| `queued` | Waiting to send |
| `sent` | Sent, waiting for response |
| `processing` | ChatGPT Pro thinking |
| `completed` | Done |
| `failed` | Failed |
| `cancelled` | Cancelled |

## ChatGPT Pro Features

* Research-grade deep analysis
* Longer thinking time
* Suitable for complex analysis and strategy design

## Use Cases

* Tasks requiring ChatGPT Pro deep analysis capabilities
* Integrating ChatGPT Pro into automation workflows
* Batch processing tasks requiring high-end AI capabilities

## Limitations

* Depends on Chrome session, may need periodic re-login
* Subject to ChatGPT rate limits
* Requires valid ChatGPT Pro subscription
* Tasks stored in memory, cleared on restart
* Chrome automation may need maintenance due to UI updates