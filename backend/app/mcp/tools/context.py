"""Tool execution context — provides data source access to MCP tool handlers.

All tool handlers read from this context, which is set during app startup.
This decouples tool definitions from data source initialization.
"""

from typing import Optional

_data_gen = None
_stream_mgr = None
_data_store = None


def set_context(data_generator=None, stream_manager=None, store=None):
    """Set the global data context for all tool handlers."""
    global _data_gen, _stream_mgr, _data_store
    _data_gen = data_generator
    _stream_mgr = stream_manager
    _data_store = store


def get_context():
    """Get the current data context."""
    return _data_gen, _stream_mgr, _data_store
