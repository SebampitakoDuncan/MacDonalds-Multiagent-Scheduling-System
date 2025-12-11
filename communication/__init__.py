"""
Communication module for inter-agent messaging.
"""
from .message import Message, MessageType
from .message_bus import MessageBus

__all__ = ["Message", "MessageType", "MessageBus"]

