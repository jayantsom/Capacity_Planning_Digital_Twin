# Yukti

Yukti is the shared AI assistant. It opens from the top navigation on every page.

## Context

Each request includes validated page context:

- Current application
- Current route
- Selected dashboard tab
- Active filters
- Selected Data Explorer table

The server decides which tools are allowed. The browser cannot add tool permissions.

Data Explorer permits schema tools and bounded read-only SQL. Planning pages permit approved analytical tools. Documentation does not permit data tools.

## Safety

- One parsed `SELECT` or approved `WITH` query
- Allowlisted published tables
- Row and time limits
- Read-only release-pinned connections
- Localhost-only write origins
- Escaped text rendering
- Sanitized public errors
- One local model request at a time

## Model

The baseline is `llama3.1:8b` through local Ollama. Yukti shows limited availability when Ollama, the model, Serving, or ML is unavailable.

## API

| Route | Purpose |
|---|---|
| `/shared/api/yukti/health` | Component health |
| `/shared/api/yukti/agents` | Available domain agents |
| `/shared/api/yukti/chat` | Complete response |
| `/shared/api/yukti/chat/stream` | SSE response stream |

Internal code remains under `operations_assistant/` because it is the assistant engine, not a standalone application.
