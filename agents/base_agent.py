"""
Base Agent class that all agents inherit from.
Provides common functionality for agent communication and lifecycle.

This module defines:
- ISchedulingAgent: Interface contract for all scheduling agents
- AgentState: Lifecycle state enumeration
- BaseAgent: Abstract base implementation

Architecture Note:
    All agents MUST implement the ISchedulingAgent interface.
    This ensures consistent behavior and enables dependency injection.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable
from rich.console import Console
from pathlib import Path
import logging
import os
import time

import sys
sys.path.append('..')

from communication.message import Message, MessageType
from communication.message_bus import MessageBus


# =============================================================================
# INTERFACE CONTRACT
# =============================================================================

@runtime_checkable
class ISchedulingAgent(Protocol):
    """
    Interface contract for all scheduling agents.
    
    All agents in the multi-agent system MUST implement this interface.
    This enables:
    - Dependency injection
    - Mock testing
    - Runtime type checking
    - Clear contract definition
    
    Usage:
        def process_with_agent(agent: ISchedulingAgent):
            if agent.health_check():
                result = agent.execute(data=my_data)
    """
    
    @property
    def name(self) -> str:
        """Agent's unique identifier."""
        ...
    
    @property
    def is_active(self) -> bool:
        """Whether the agent is currently active."""
        ...
    
    def execute(self, **kwargs) -> Any:
        """Execute the agent's main task."""
        ...
    
    def health_check(self) -> bool:
        """Check if the agent is healthy and ready to process."""
        ...
    
    def startup(self) -> None:
        """Initialize and start the agent."""
        ...
    
    def shutdown(self) -> None:
        """Gracefully shut down the agent."""
        ...
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get agent performance metrics."""
        ...
    
    def learn_from_outcome(self, action: str, outcome: str, context: Dict) -> None:
        """Learn from action outcomes for emergent behavior."""
        ...


# =============================================================================
# EMERGENT BEHAVIOR TRACKING
# =============================================================================

class EmergentBehaviorTracker:
    """
    Tracks patterns and enables emergent collaborative behavior.
    
    Emergent behavior arises when agents learn from:
    - Successful resolutions
    - Failed attempts
    - Negotiation outcomes
    - Pattern recognition
    
    This creates adaptive behavior without explicit programming.
    """
    
    def __init__(self):
        self.action_outcomes: Dict[str, List[Dict]] = {}  # action -> outcomes
        self.pattern_cache: Dict[str, float] = {}  # pattern -> success rate
        self.collaboration_scores: Dict[str, float] = {}  # agent pair -> score
    
    def record_outcome(self, agent: str, action: str, 
                      outcome: str, context: Dict) -> None:
        """
        Record an action outcome for learning.
        
        Args:
            agent: Name of the agent
            action: Action taken (e.g., "swap_employee", "add_shift")
            outcome: Result ("success", "failure", "partial")
            context: Additional context (violation type, employee type, etc.)
        """
        key = f"{agent}:{action}"
        if key not in self.action_outcomes:
            self.action_outcomes[key] = []
        
        self.action_outcomes[key].append({
            "outcome": outcome,
            "context": context,
            "timestamp": time.time()
        })
        
        # Update pattern cache
        self._update_patterns(agent, action, outcome, context)
    
    def _update_patterns(self, agent: str, action: str, 
                        outcome: str, context: Dict) -> None:
        """Update pattern success rates based on new outcome."""
        # Create pattern key from context
        pattern_key = self._create_pattern_key(action, context)
        
        if pattern_key not in self.pattern_cache:
            self.pattern_cache[pattern_key] = 0.5  # Start neutral
        
        # Update with exponential moving average
        success = 1.0 if outcome == "success" else 0.0
        alpha = 0.3  # Learning rate
        self.pattern_cache[pattern_key] = (
            alpha * success + (1 - alpha) * self.pattern_cache[pattern_key]
        )
    
    def _create_pattern_key(self, action: str, context: Dict) -> str:
        """Create a pattern key from action and context."""
        # Extract relevant context features
        violation_type = context.get("violation_type", "unknown")
        employee_type = context.get("employee_type", "any")
        day_type = context.get("day_type", "weekday")  # weekday/weekend
        
        return f"{action}|{violation_type}|{employee_type}|{day_type}"
    
    def get_action_recommendation(self, action: str, context: Dict) -> float:
        """
        Get recommendation score for an action based on learned patterns.
        
        Returns:
            Score between 0-1 (higher = more recommended)
        """
        pattern_key = self._create_pattern_key(action, context)
        return self.pattern_cache.get(pattern_key, 0.5)
    
    def record_collaboration(self, agent1: str, agent2: str, 
                            success: bool) -> None:
        """Record collaboration outcome between two agents."""
        key = f"{agent1}<->{agent2}"
        if key not in self.collaboration_scores:
            self.collaboration_scores[key] = 0.5
        
        score = 1.0 if success else 0.0
        alpha = 0.2
        self.collaboration_scores[key] = (
            alpha * score + (1 - alpha) * self.collaboration_scores[key]
        )
    
    def get_emergent_summary(self) -> Dict[str, Any]:
        """Get summary of emergent behaviors detected."""
        # Find most successful patterns
        top_patterns = sorted(
            self.pattern_cache.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:5]
        
        # Find best collaborations
        top_collabs = sorted(
            self.collaboration_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )[:3]
        
        return {
            "patterns_learned": len(self.pattern_cache),
            "total_outcomes_recorded": sum(len(v) for v in self.action_outcomes.values()),
            "top_successful_patterns": [
                {"pattern": p, "success_rate": f"{s:.1%}"} 
                for p, s in top_patterns
            ],
            "best_collaborations": [
                {"agents": a, "score": f"{s:.1%}"} 
                for a, s in top_collabs
            ],
        }


# Global emergent behavior tracker (shared across agents)
emergent_tracker = EmergentBehaviorTracker()


class AgentState(Enum):
    """Agent lifecycle states."""
    INITIALIZING = "initializing"
    IDLE = "idle"
    PROCESSING = "processing"
    WAITING = "waiting"
    COMPLETED = "completed"
    ERROR = "error"
    SHUTDOWN = "shutdown"


class BaseAgent(ABC):
    """
    Abstract base class for all agents in the scheduling system.
    
    Provides:
    - Message sending/receiving via MessageBus
    - State management with explicit lifecycle
    - Dual logging (console + file)
    - Error handling with graceful degradation
    - Standard lifecycle methods
    
    Attributes:
        name: Unique identifier for the agent
        message_bus: Reference to the central message bus
        state: Agent's internal state dict
        agent_state: Current lifecycle state (AgentState enum)
        is_active: Whether the agent is currently active
    """
    
    # Class-level file logger (shared across all agents)
    _file_logger: Optional[logging.Logger] = None
    _log_file_path: Optional[str] = None
    
    @classmethod
    def setup_file_logging(cls, log_dir: str = "output") -> str:
        """
        Set up file logging for all agents.
        
        Args:
            log_dir: Directory for log files
            
        Returns:
            Path to the log file
        """
        if cls._file_logger is not None:
            return cls._log_file_path
        
        # Create log directory
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        
        # Create log file with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"scheduling_log_{timestamp}.txt")
        
        # Set up logger
        cls._file_logger = logging.getLogger("MultiAgentScheduler")
        cls._file_logger.setLevel(logging.DEBUG)
        
        # File handler
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        cls._file_logger.addHandler(file_handler)
        cls._log_file_path = log_file
        
        # Log header
        cls._file_logger.info("=" * 70)
        cls._file_logger.info("McDONALD'S MULTI-AGENT SCHEDULING SYSTEM - LOG FILE")
        cls._file_logger.info(f"Session started: {datetime.now().isoformat()}")
        cls._file_logger.info("=" * 70)
        
        return log_file
    
    def __init__(self, name: str, message_bus: MessageBus):
        """
        Initialize the agent.
        
        Args:
            name: Unique name for this agent
            message_bus: The central message bus for communication
        """
        self.name = name
        self.message_bus = message_bus
        self.state: Dict[str, Any] = {}
        self.agent_state = AgentState.INITIALIZING
        self.is_active = True
        self.console = Console()
        self._message_handlers: Dict[MessageType, Callable] = {}
        self._error_count = 0
        self._max_errors = 3  # Graceful degradation threshold
        
        # Register with message bus
        self.message_bus.register(self.name, self._handle_message)
        
        # Set up default message handlers
        self._setup_handlers()
        
        # Log startup
        self._transition_state(AgentState.IDLE)
        self.log(f"Agent initialized and ready", "debug")
    
    def _setup_handlers(self) -> None:
        """Set up message type handlers. Override in subclasses."""
        self._message_handlers = {
            MessageType.REQUEST: self._on_request,
            MessageType.BROADCAST: self._on_broadcast,
            MessageType.DATA: self._on_data,
            MessageType.VALIDATION_REQUEST: self._on_validation_request,
            MessageType.VALIDATION_RESULT: self._on_validation_result,
            MessageType.SCHEDULE: self._on_schedule,
            MessageType.VIOLATION: self._on_violation,
            MessageType.RESOLUTION_SELECTED: self._on_resolution,
            MessageType.COMPLETE: self._on_complete,
        }
    
    def _handle_message(self, message: Message) -> None:
        """
        Handle incoming messages by routing to appropriate handler.
        
        Args:
            message: The incoming message
        """
        handler = self._message_handlers.get(message.msg_type)
        if handler:
            handler(message)
        else:
            self._on_unknown_message(message)
    
    # ==================== Message Handlers (Override in subclasses) ====================
    
    def _on_request(self, message: Message) -> None:
        """Handle REQUEST messages. Override in subclasses."""
        pass
    
    def _on_broadcast(self, message: Message) -> None:
        """Handle BROADCAST messages. Override in subclasses."""
        pass
    
    def _on_data(self, message: Message) -> None:
        """Handle DATA messages. Override in subclasses."""
        pass
    
    def _on_validation_request(self, message: Message) -> None:
        """Handle VALIDATION_REQUEST messages. Override in subclasses."""
        pass
    
    def _on_validation_result(self, message: Message) -> None:
        """Handle VALIDATION_RESULT messages. Override in subclasses."""
        pass
    
    def _on_schedule(self, message: Message) -> None:
        """Handle SCHEDULE messages. Override in subclasses."""
        pass
    
    def _on_violation(self, message: Message) -> None:
        """Handle VIOLATION messages. Override in subclasses."""
        pass
    
    def _on_resolution(self, message: Message) -> None:
        """Handle RESOLUTION_SELECTED messages. Override in subclasses."""
        pass
    
    def _on_complete(self, message: Message) -> None:
        """Handle COMPLETE messages. Override in subclasses."""
        pass
    
    def _on_unknown_message(self, message: Message) -> None:
        """Handle unknown message types."""
        self.log(f"Received unknown message type: {message.msg_type}", level="warning")
    
    # ==================== Message Sending ====================
    
    def send(self, 
             msg_type: MessageType, 
             content: Any, 
             receiver: Optional[str] = None,
             correlation_id: Optional[str] = None,
             metadata: Optional[dict] = None) -> Message:
        """
        Send a message through the message bus.
        
        Args:
            msg_type: Type of message
            content: Message payload
            receiver: Target agent (None for broadcast)
            correlation_id: ID for tracking conversation threads
            metadata: Additional metadata
            
        Returns:
            The sent message
        """
        message = Message(
            msg_type=msg_type,
            sender=self.name,
            receiver=receiver,
            content=content,
            metadata=metadata or {}
        )
        
        if correlation_id:
            message.correlation_id = correlation_id
        
        # Log explicit bus activity to the main file logger for auditing/demo
        if BaseAgent._file_logger:
            preview = str(content)
            if len(preview) > 120:
                preview = preview[:120] + "..."
            BaseAgent._file_logger.info(
                "[MessageBus] %s → %s (%s) correlation=%s | %s",
                self.name,
                receiver or "ALL",
                msg_type.value,
                message.correlation_id or "-",
                preview,
            )
        
        self.message_bus.send(message)
        return message
    
    def respond(self, original: Message, content: Any, 
                msg_type: MessageType = MessageType.RESPONSE) -> Message:
        """
        Send a response to a message.
        
        Args:
            original: The message being responded to
            content: Response content
            msg_type: Type of response message
            
        Returns:
            The response message
        """
        response = Message.create_response(original, content, msg_type)
        response.sender = self.name
        
        # Log explicit bus activity for responses as well
        if BaseAgent._file_logger:
            preview = str(content)
            if len(preview) > 120:
                preview = preview[:120] + "..."
            BaseAgent._file_logger.info(
                "[MessageBus] %s → %s (%s) correlation=%s | %s",
                self.name,
                response.receiver or "ALL",
                msg_type.value,
                response.correlation_id or "-",
                preview,
            )
        
        self.message_bus.send(response)
        return response
    
    def broadcast(self, content: Any, msg_type: MessageType = MessageType.BROADCAST) -> Message:
        """
        Broadcast a message to all agents.
        
        Args:
            content: Message content
            msg_type: Type of message
            
        Returns:
            The broadcast message
        """
        return self.send(msg_type, content, receiver=None)
    
    # ==================== Data State Management ====================
    
    def set_data(self, key: str, value: Any) -> None:
        """Set a value in the agent's data state."""
        self.state[key] = value
    
    def get_data(self, key: str, default: Any = None) -> Any:
        """Get a value from the agent's data state."""
        return self.state.get(key, default)
    
    def clear_data(self) -> None:
        """Clear all data state."""
        self.state = {}
    
    # ==================== Lifecycle ====================
    
    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """
        Execute the agent's main task.
        Override in subclasses to implement specific behavior.
        
        Returns:
            Result of the agent's execution
        """
        pass
    
    def startup(self) -> None:
        """
        Start up the agent (explicit lifecycle protocol).
        Called before first execution.
        """
        self.is_active = True
        self._error_count = 0
        self._transition_state(AgentState.IDLE)
        self.log(f"🟢 Agent started", "success")
        
        if BaseAgent._file_logger:
            BaseAgent._file_logger.info(f"[{self.name}] STARTUP - Agent ready")
    
    def activate(self) -> None:
        """Activate the agent."""
        self.is_active = True
        self._transition_state(AgentState.IDLE)
        self.log("Agent activated")
    
    def deactivate(self) -> None:
        """Deactivate the agent."""
        self.is_active = False
        self._transition_state(AgentState.IDLE)
        self.log("Agent deactivated")
    
    def shutdown(self) -> None:
        """
        Shut down the agent (explicit lifecycle protocol).
        Unregisters from message bus and logs final status.
        """
        self._transition_state(AgentState.SHUTDOWN)
        self.deactivate()
        self.message_bus.unregister(self.name)
        
        self.log(f"🔴 Agent shutdown (errors: {self._error_count})", "info")
        
        if BaseAgent._file_logger:
            BaseAgent._file_logger.info(
                f"[{self.name}] SHUTDOWN - Final state: {self.agent_state.value}, Errors: {self._error_count}"
            )
    
    def health_check(self) -> bool:
        """
        Check if the agent is healthy and ready to process.
        
        Implements ISchedulingAgent.health_check()
        
        Returns:
            True if agent is healthy, False otherwise
        """
        is_healthy = (
            self.is_active and 
            self.agent_state not in [AgentState.ERROR, AgentState.SHUTDOWN] and
            self._error_count < self._max_errors
        )
        return is_healthy
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get agent performance metrics.
        
        Implements ISchedulingAgent.get_metrics()
        
        Returns:
            Dictionary with performance metrics
        """
        return {
            "name": self.name,
            "state": self.agent_state.value,
            "is_active": self.is_active,
            "error_count": self._error_count,
            "max_errors": self._max_errors,
            "is_healthy": self.health_check(),
            "execution_time": getattr(self, '_last_execution_time', None),
        }
    
    # ==================== Logging ====================
    
    def log(self, message: str, level: str = "info") -> None:
        """
        Log a message with agent context (dual: console + file).
        
        Args:
            message: The log message
            level: Log level (info, warning, error, debug, success)
        """
        # Console logging with colors
        colors = {
            "info": "blue",
            "warning": "yellow", 
            "error": "red",
            "debug": "dim",
            "success": "green"
        }
        color = colors.get(level, "white")
        self.console.print(f"[{color}][{self.name}] {message}[/{color}]")
        
        # File logging
        if BaseAgent._file_logger:
            log_level = {
                "info": logging.INFO,
                "warning": logging.WARNING,
                "error": logging.ERROR,
                "debug": logging.DEBUG,
                "success": logging.INFO,
            }.get(level, logging.INFO)
            
            BaseAgent._file_logger.log(log_level, f"[{self.name}] {message}")
    
    # ==================== State Management ====================
    
    def _transition_state(self, new_state: AgentState) -> None:
        """
        Transition to a new agent state with logging.
        
        Args:
            new_state: The new state to transition to
        """
        old_state = self.agent_state
        self.agent_state = new_state
        
        if BaseAgent._file_logger:
            BaseAgent._file_logger.debug(
                f"[{self.name}] State: {old_state.value} → {new_state.value}"
            )
    
    def get_agent_state(self) -> AgentState:
        """Get the current agent lifecycle state."""
        return self.agent_state
    
    # ==================== Error Handling ====================
    
    def _handle_error(self, error: Exception, context: str = "") -> bool:
        """
        Handle an error with graceful degradation.
        
        Args:
            error: The exception that occurred
            context: Description of what was happening when error occurred
            
        Returns:
            True if agent can continue, False if should stop
        """
        self._error_count += 1
        self._transition_state(AgentState.ERROR)
        
        error_msg = f"Error in {context}: {type(error).__name__}: {str(error)}"
        self.log(error_msg, "error")
        
        if BaseAgent._file_logger:
            import traceback
            BaseAgent._file_logger.error(f"[{self.name}] {error_msg}")
            BaseAgent._file_logger.error(f"[{self.name}] Traceback:\n{traceback.format_exc()}")
        
        # Graceful degradation: allow up to max_errors before failing
        if self._error_count >= self._max_errors:
            self.log(f"Max errors ({self._max_errors}) reached - agent degraded", "warning")
            return False
        
        self.log(f"Error {self._error_count}/{self._max_errors} - continuing with degraded mode", "warning")
        self._transition_state(AgentState.IDLE)
        return True
    
    def safe_execute(self, **kwargs) -> Any:
        """
        Execute with error handling and graceful degradation.
        
        Wraps the execute() method with try/catch and state management.
        
        Returns:
            Result of execute() or None if error occurred
        """
        try:
            self._transition_state(AgentState.PROCESSING)
            result = self.execute(**kwargs)
            self._transition_state(AgentState.COMPLETED)
            return result
        except Exception as e:
            can_continue = self._handle_error(e, "execute()")
            if not can_continue:
                raise
            return None
    
    # ==================== Utility Methods ====================
    
    def __str__(self) -> str:
        status = "active" if self.is_active else "inactive"
        return f"{self.name} ({self.__class__.__name__}, {status})"
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}', active={self.is_active})>"

