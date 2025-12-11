"""
Configuration file for the McDonald's Multi-Agent Scheduling System.

This file contains API keys, model configurations, and other settings.
Keep this file secure and do not commit API keys to version control.

SECURITY: API keys should ALWAYS be loaded from environment variables.
"""

import os
import time
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Any
from functools import wraps

# =============================================================================
# SECURITY: API KEY CONFIGURATION
# =============================================================================


def get_api_key() -> str:
    """
    Get the OpenRouter API key from environment variable.
    
    Security best practice: API keys should only come from environment variables,
    not from source code.
    
    Returns:
        API key string, or empty string if not set
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        logging.warning(
            "⚠️  OPENROUTER_API_KEY environment variable not set. "
            "LLM features will use template-based fallback. "
            "Set it with: export OPENROUTER_API_KEY='your-key-here'"
        )
    return api_key


# =============================================================================
# RATE LIMITING
# =============================================================================

class RateLimiter:
    """
    Simple rate limiter to prevent API cost explosion.
    
    Implements a token bucket algorithm for rate limiting API calls.
    """
    
    def __init__(self, max_calls: int = 10, period_seconds: float = 60.0):
        """
        Initialize rate limiter.
        
        Args:
            max_calls: Maximum calls allowed in the period
            period_seconds: Time period in seconds
        """
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self.calls: List[float] = []
    
    def acquire(self) -> bool:
        """
        Try to acquire a rate limit token.
        
        Returns:
            True if call is allowed, False if rate limited
        """
        now = time.time()
        
        # Remove calls outside the current window
        self.calls = [t for t in self.calls if now - t < self.period_seconds]
        
        if len(self.calls) >= self.max_calls:
            return False
        
        self.calls.append(now)
        return True
    
    def wait_if_needed(self) -> None:
        """Block until a call is allowed."""
        while not self.acquire():
            time.sleep(0.5)
    
    def remaining(self) -> int:
        """Get remaining calls in current window."""
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.period_seconds]
        return max(0, self.max_calls - len(self.calls))


# Global rate limiter for LLM calls (10 calls per minute for free tier)
llm_rate_limiter = RateLimiter(max_calls=10, period_seconds=60.0)


# =============================================================================
# RETRY WITH EXPONENTIAL BACKOFF
# =============================================================================

def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,)
) -> Callable:
    """
    Decorator for retrying functions with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        exponential_base: Base for exponential calculation
        exceptions: Tuple of exceptions to catch and retry
    
    Returns:
        Decorated function with retry logic
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        # Calculate delay with exponential backoff
                        delay = min(
                            base_delay * (exponential_base ** attempt),
                            max_delay
                        )
                        
                        logging.warning(
                            f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logging.error(
                            f"All {max_retries + 1} attempts failed. Last error: {e}"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator


# =============================================================================
# HEALTH CHECK SYSTEM
# =============================================================================

@dataclass
class HealthStatus:
    """Health status of a system component."""
    name: str
    healthy: bool
    message: str
    last_check: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "healthy": self.healthy,
            "message": self.message,
            "last_check_seconds_ago": time.time() - self.last_check
        }


class HealthChecker:
    """
    System health checker for monitoring component status.
    
    Provides health checks for:
    - API connectivity
    - File system access
    - Memory usage
    - Agent status
    """
    
    def __init__(self):
        self.checks: List[HealthStatus] = []
    
    def check_api_key(self) -> HealthStatus:
        """Check if API key is configured."""
        api_key = get_api_key()
        if api_key:
            return HealthStatus(
                name="api_key",
                healthy=True,
                message="API key configured"
            )
        return HealthStatus(
            name="api_key",
            healthy=False,
            message="API key not set (LLM features disabled)"
        )
    
    def check_data_directory(self, data_dir: str = "data") -> HealthStatus:
        """Check if data directory exists and is readable."""
        if os.path.exists(data_dir) and os.path.isdir(data_dir):
            files = os.listdir(data_dir)
            csv_files = [f for f in files if f.endswith('.csv')]
            return HealthStatus(
                name="data_directory",
                healthy=True,
                message=f"Data directory OK ({len(csv_files)} CSV files)"
            )
        return HealthStatus(
            name="data_directory",
            healthy=False,
            message=f"Data directory not found: {data_dir}"
        )
    
    def check_output_directory(self, output_dir: str = "output") -> HealthStatus:
        """Check if output directory is writable."""
        try:
            os.makedirs(output_dir, exist_ok=True)
            test_file = os.path.join(output_dir, ".health_check")
            with open(test_file, 'w') as f:
                f.write("health check")
            os.remove(test_file)
            return HealthStatus(
                name="output_directory",
                healthy=True,
                message="Output directory writable"
            )
        except Exception as e:
            return HealthStatus(
                name="output_directory",
                healthy=False,
                message=f"Output directory error: {e}"
            )
    
    def check_rate_limit(self) -> HealthStatus:
        """Check rate limiter status."""
        remaining = llm_rate_limiter.remaining()
        if remaining > 0:
            return HealthStatus(
                name="rate_limit",
                healthy=True,
                message=f"Rate limit OK ({remaining} calls remaining)"
            )
        return HealthStatus(
            name="rate_limit",
            healthy=False,
            message="Rate limit exhausted (wait before making more calls)"
        )
    
    def run_all_checks(self, data_dir: str = "data", output_dir: str = "output") -> dict:
        """
        Run all health checks and return summary.
        
        Returns:
            Dictionary with overall status and individual check results
        """
        checks = [
            self.check_api_key(),
            self.check_data_directory(data_dir),
            self.check_output_directory(output_dir),
            self.check_rate_limit(),
        ]
        
        all_healthy = all(c.healthy for c in checks)
        critical_healthy = all(
            c.healthy for c in checks 
            if c.name in ["data_directory", "output_directory"]
        )
        
        return {
            "status": "healthy" if all_healthy else ("degraded" if critical_healthy else "unhealthy"),
            "timestamp": time.time(),
            "checks": [c.to_dict() for c in checks]
        }


# Global health checker instance
health_checker = HealthChecker()


# =============================================================================
# LLM CONFIGURATION
# =============================================================================

@dataclass
class LLMConfig:
    """Configuration for LLM (Language Model) integration."""
    
    # OpenRouter API Configuration
    base_url: str = "https://openrouter.ai/api/v1"
    
    # Model selection (using free models from OpenRouter)
    primary_model: str = "mistralai/mistral-7b-instruct:free" #mistralai/mistral-7b-instruct:free
    fallback_model: str = "google/gemma-2-9b-it:free" #google/gemma-2-9b-it:free
    
    # Request settings
    max_tokens: int = 300
    temperature: float = 0.7
    
    # Retry settings (used by retry_with_backoff decorator)
    max_retries: int = 3
    base_delay: float = 1.0
    retry_delay: float = 1.0  # Alias for base_delay (backwards compatibility)
    
    @property
    def api_key(self) -> str:
        """Get API key from environment (never stored in config)."""
        return get_api_key()


# =============================================================================
# SCHEDULING CONFIGURATION
# =============================================================================

@dataclass
class SchedulingConfig:
    """Configuration for scheduling parameters."""
    
    # Fair Work Act compliance
    min_rest_hours: int = 10
    max_consecutive_days: int = 6
    min_shift_hours: int = 3
    max_shift_hours: int = 12
    
    # Weekly hours limits by employee type
    full_time_hours: tuple = (35, 38)
    part_time_hours: tuple = (20, 32)
    casual_hours: tuple = (8, 24)
    
    # Staffing requirements
    min_staff_on_duty: int = 2
    min_full_time_on_duty: int = 1
    
    # Coverage settings
    weekend_multiplier: float = 1.2
    peak_multiplier: float = 1.3


# =============================================================================
# MAIN APPLICATION CONFIGURATION
# =============================================================================

@dataclass
class AppConfig:
    """Main application configuration."""
    
    llm: LLMConfig = field(default_factory=LLMConfig)
    scheduling: SchedulingConfig = field(default_factory=SchedulingConfig)
    
    # Output settings
    output_dir: str = "output"
    verbose: bool = True
    
    # Performance settings
    max_iterations: int = 5
    target_time_seconds: int = 180
    
    @classmethod
    def load(cls) -> "AppConfig":
        """Load configuration from environment and defaults."""
        return cls()


# Global configuration instance
config = AppConfig.load()


# =============================================================================
# USAGE INSTRUCTIONS
# =============================================================================
#
# 1. Set your API key as an environment variable:
#
#    export OPENROUTER_API_KEY="your-api-key-here"
#
# 2. Or add to your shell profile for persistence:
#
#    echo 'export OPENROUTER_API_KEY="your-key"' >> ~/.zshrc
#    source ~/.zshrc
#
# 3. Get your free API key at: https://openrouter.ai/keys
#
# =============================================================================
