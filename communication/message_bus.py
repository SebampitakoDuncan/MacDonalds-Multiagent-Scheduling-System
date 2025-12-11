"""
Message Bus for agent communication.
Central hub that routes messages between agents and maintains communication logs.
"""
from collections import defaultdict
from datetime import datetime
from typing import Callable, Dict, List, Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .message import Message, MessageType


class MessageBus:
    """
    Central message bus for inter-agent communication.
    
    Features:
    - Message routing between agents
    - Broadcast capability
    - Message history logging
    - Subscription-based message handling
    """
    
    def __init__(self, verbose: bool = True):
        """
        Initialize the message bus.
        
        Args:
            verbose: Whether to print messages to console
        """
        self.subscribers: Dict[str, Callable[[Message], None]] = {}
        self.message_history: List[Message] = []
        self.verbose = verbose
        self.console = Console()
        
    def register(self, agent_name: str, handler: Callable[[Message], None]) -> None:
        """
        Register an agent to receive messages.
        
        Args:
            agent_name: Unique name of the agent
            handler: Callback function to handle incoming messages
        """
        self.subscribers[agent_name] = handler
        if self.verbose:
            self.console.print(f"[dim]📡 Agent registered: {agent_name}[/dim]")
    
    def unregister(self, agent_name: str) -> None:
        """Remove an agent from the message bus."""
        if agent_name in self.subscribers:
            del self.subscribers[agent_name]
            
    def send(self, message: Message) -> None:
        """
        Send a message to a specific agent or broadcast to all.
        
        Args:
            message: The message to send
        """
        # Log the message
        self.message_history.append(message)
        
        # Print if verbose
        if self.verbose:
            self._print_message(message)
        
        # Route the message
        if message.receiver is None:
            # Broadcast to all agents except sender
            for agent_name, handler in self.subscribers.items():
                if agent_name != message.sender:
                    handler(message)
        else:
            # Send to specific agent
            if message.receiver in self.subscribers:
                self.subscribers[message.receiver](message)
            else:
                self.console.print(
                    f"[red]⚠️ Agent '{message.receiver}' not found![/red]"
                )
    
    def _print_message(self, message: Message) -> None:
        """Pretty print a message to console."""
        # Color coding by message type
        type_colors = {
            MessageType.REQUEST: "cyan",
            MessageType.RESPONSE: "green",
            MessageType.VIOLATION: "red",
            MessageType.CONFLICT: "yellow",
            MessageType.RESOLUTION_OPTIONS: "magenta",
            MessageType.COMPLETE: "green",
            MessageType.ERROR: "red",
            MessageType.APPROVAL_REQUEST: "yellow",
        }
        
        color = type_colors.get(message.msg_type, "white")
        receiver = message.receiver or "ALL"
        
        # Format content preview
        content_str = str(message.content)
        if len(content_str) > 150:
            content_str = content_str[:150] + "..."
        
        self.console.print(
            f"[dim]{message.timestamp.strftime('%H:%M:%S.%f')[:-3]}[/dim] "
            f"[bold]{message.sender}[/bold] → [bold]{receiver}[/bold] "
            f"[{color}]({message.msg_type.value})[/{color}]"
        )
        if content_str and message.msg_type != MessageType.DATA:
            self.console.print(f"  [dim]└─ {content_str}[/dim]")
    
    def get_history(self, 
                    sender: Optional[str] = None,
                    receiver: Optional[str] = None,
                    msg_type: Optional[MessageType] = None) -> List[Message]:
        """
        Get filtered message history.
        
        Args:
            sender: Filter by sender agent
            receiver: Filter by receiver agent
            msg_type: Filter by message type
            
        Returns:
            List of messages matching the filters
        """
        messages = self.message_history
        
        if sender:
            messages = [m for m in messages if m.sender == sender]
        if receiver:
            messages = [m for m in messages if m.receiver == receiver]
        if msg_type:
            messages = [m for m in messages if m.msg_type == msg_type]
            
        return messages
    
    def get_conversation(self, correlation_id: str) -> List[Message]:
        """Get all messages in a conversation thread."""
        return [m for m in self.message_history if m.correlation_id == correlation_id]
    
    def print_summary(self) -> None:
        """Print a summary of all agent communications."""
        table = Table(title="📊 Agent Communication Summary")
        table.add_column("Agent", style="cyan")
        table.add_column("Messages Sent", justify="right")
        table.add_column("Messages Received", justify="right")
        
        # Count messages per agent
        sent_count = defaultdict(int)
        received_count = defaultdict(int)
        
        for msg in self.message_history:
            sent_count[msg.sender] += 1
            if msg.receiver:
                received_count[msg.receiver] += 1
            else:
                # Broadcast - count for all except sender
                for agent in self.subscribers:
                    if agent != msg.sender:
                        received_count[agent] += 1
        
        for agent in self.subscribers:
            table.add_row(
                agent,
                str(sent_count[agent]),
                str(received_count[agent])
            )
        
        self.console.print(table)
    
    def export_log(self) -> List[dict]:
        """Export message history as list of dictionaries."""
        return [msg.to_dict() for msg in self.message_history]
    
    def clear_history(self) -> None:
        """Clear message history."""
        self.message_history = []

