"""
Message protocol for inter-agent communication.
Defines the structure of messages exchanged between agents.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import uuid


class MessageType(Enum):
    """Types of messages that agents can exchange."""
    
    # Workflow messages
    REQUEST = "request"           # Request an agent to perform a task
    RESPONSE = "response"         # Response to a request
    BROADCAST = "broadcast"       # Message to all agents
    
    # Data messages
    DATA = "data"                 # Data payload (employees, shifts, etc.)
    SCHEDULE = "schedule"         # Schedule proposal
    
    # Validation messages
    VALIDATION_REQUEST = "validation_request"
    VALIDATION_RESULT = "validation_result"
    VIOLATION = "violation"       # Constraint violation detected
    
    # Conflict resolution
    CONFLICT = "conflict"         # Conflict detected
    RESOLUTION_OPTIONS = "resolution_options"
    RESOLUTION_SELECTED = "resolution_selected"
    
    # Status messages
    STATUS = "status"             # Agent status update
    ERROR = "error"               # Error occurred
    COMPLETE = "complete"         # Task completed
    
    # Human-in-the-loop
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_RESPONSE = "approval_response"
    
    # Agent Negotiation Protocol
    NEGOTIATE_PROPOSE = "negotiate_propose"     # Agent proposes a solution
    NEGOTIATE_COUNTER = "negotiate_counter"     # Counter-proposal
    NEGOTIATE_ACCEPT = "negotiate_accept"       # Accept proposal
    NEGOTIATE_REJECT = "negotiate_reject"       # Reject proposal
    
    # Bidding/Auction
    BID_REQUEST = "bid_request"                 # Request bids for a shift
    BID_SUBMIT = "bid_submit"                   # Submit a bid
    BID_RESULT = "bid_result"                   # Auction result


@dataclass
class Message:
    """
    Message structure for agent communication.
    
    Attributes:
        msg_type: Type of the message
        sender: Name of the sending agent
        receiver: Name of the receiving agent (None for broadcast)
        content: Message payload
        correlation_id: ID to track related messages
        timestamp: When the message was created
        metadata: Additional message metadata
    """
    msg_type: MessageType
    sender: str
    receiver: Optional[str]
    content: Any
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)
    
    def __str__(self) -> str:
        """Human-readable message representation."""
        receiver_str = self.receiver or "ALL"
        content_preview = str(self.content)[:100]
        if len(str(self.content)) > 100:
            content_preview += "..."
        return (
            f"[{self.timestamp.strftime('%H:%M:%S')}] "
            f"{self.sender} → {receiver_str} "
            f"({self.msg_type.value}): {content_preview}"
        )
    
    def to_dict(self) -> dict:
        """Convert message to dictionary for logging/serialization."""
        return {
            "msg_type": self.msg_type.value,
            "sender": self.sender,
            "receiver": self.receiver,
            "content": self.content,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }
    
    @classmethod
    def create_response(cls, original: "Message", content: Any, 
                        msg_type: MessageType = MessageType.RESPONSE) -> "Message":
        """Create a response message to an original message."""
        return cls(
            msg_type=msg_type,
            sender=original.receiver,
            receiver=original.sender,
            content=content,
            correlation_id=original.correlation_id,
            metadata={"in_response_to": original.msg_type.value}
        )

