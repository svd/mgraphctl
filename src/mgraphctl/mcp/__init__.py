"""The MCP server: the CLI's verbs as Model Context Protocol tools.

Design: `docs/specs/2026-09-07-mcp-server-design.md`. Only `discover` and `schema` are importable
without the `mgraphctl[mcp]` extra; `server` and `http_app` need the SDK.
"""
