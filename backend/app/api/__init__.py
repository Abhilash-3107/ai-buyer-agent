"""Phase 6 HTTP API (D41-D44): a window onto the same agent, trace, database and scorer the CLI and eval use.

`app.py` builds the FastAPI app, `routes.py` holds the endpoints and the read model they serve, `registry.py` the
in-process run registry (background thread, SSE events, `.api.json` sidecars) and `types.py` the request bodies.
No business logic lives here.
"""
