"""
Configuration management for the Twitch Discord Bot.

This module handles all configuration settings, validation, and provides
a centralized place for managing environment variables and constants.
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)

logger = logging.getLogger(__name__)

class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing."""
    pass

class Config:
    """Configuration class for the Twitch Discord Bot."""
    
    # Required environment variables
    DISCORD_BOT_TOKEN: str
    TWITCH_CLIENT_ID: str
    TWITCH_CLIENT_SECRET: str
    
    # Optional environment variables with defaults
    REDIRECT_URI: str = "http://localhost:8000/callback"
    TWITCH_USERNAME: str = "notrheddev"
    STREAM_NOTIFICATION_CHANNEL_ID: Optional[str] = None
    STREAM_NOTIFICATION_ROLE_ID: Optional[str] = None
    DISCORD_WELCOME_CHANNEL_ID: Optional[str] = None
    
    # Application constants
    OAUTH_TIMEOUT_SECONDS: int = 300  # 5 minutes
    OAUTH_POLL_INTERVAL_SECONDS: int = 2
    MAX_RECONNECT_ATTEMPTS: int = 5
    RECONNECT_BASE_DELAY_SECONDS: int = 1
    RECONNECT_MAX_DELAY_SECONDS: int = 30
    FASTAPI_HOST: str = "0.0.0.0"
    FASTAPI_PORT: int = 8000
    
    # Scopes required for Twitch API
    REQUIRED_TWITCH_SCOPES = ["channel:read:subscriptions"]
    
    # Discord embed constants
    DISCORD_EMBED_COLOR = 0x9146FF  # Twitch purple
    DISCORD_EMBED_FOOTER = "Made with ❤️ by RhedDev"
    
    # Twitch URL constants
    TWITCH_BASE_URL = "https://twitch.tv"
    TWITCH_EVENTSUB_URL = "wss://eventsub.wss.twitch.tv/ws"
    
    def __init__(self):
        """Initialize configuration and validate required settings."""
        self._load_configuration()
        self._validate_configuration()
    
    def _load_configuration(self) -> None:
        """Load configuration from environment variables."""
        # Required settings
        self.DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')
        self.TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID', '')
        self.TWITCH_CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET', '')
        
        # Optional settings
        self.REDIRECT_URI = os.getenv('REDIRECT_URI', self.REDIRECT_URI)
        self.TWITCH_USERNAME = os.getenv('TWITCH_USERNAME', self.TWITCH_USERNAME)
        self.STREAM_NOTIFICATION_CHANNEL_ID = os.getenv('STREAM_NOTIFICATION_CHANNEL_ID')
        self.STREAM_NOTIFICATION_ROLE_ID = os.getenv('STREAM_NOTIFICATION_ROLE_ID')
        self.DISCORD_WELCOME_CHANNEL_ID = os.getenv('DISCORD_WELCOME_CHANNEL_ID')
        
        logger.info("Configuration loaded from environment variables")
    
    def _validate_configuration(self) -> None:
        """Validate that all required configuration is present."""
        errors = []
        
        if not self.DISCORD_BOT_TOKEN:
            errors.append("DISCORD_BOT_TOKEN is required")
        
        if not self.TWITCH_CLIENT_ID:
            errors.append("TWITCH_CLIENT_ID is required")
        
        if not self.TWITCH_CLIENT_SECRET:
            errors.append("TWITCH_CLIENT_SECRET is required")
        
        if not self.TWITCH_USERNAME:
            errors.append("TWITCH_USERNAME cannot be empty")
        
        if errors:
            error_message = "Configuration validation failed:\n" + "\n".join(f"- {error}" for error in errors)
            logger.error(error_message)
            raise ConfigurationError(error_message)
        
        logger.info("Configuration validation successful")
    
    def get_twitch_stream_url(self, username: str) -> str:
        """Get the Twitch stream URL for a given username."""
        return f"{self.TWITCH_BASE_URL}/{username.lower()}"
    
    def get_oauth_timeout_info(self) -> tuple[int, int]:
        """Get OAuth timeout configuration as (max_wait_seconds, poll_interval_seconds)."""
        return self.OAUTH_TIMEOUT_SECONDS, self.OAUTH_POLL_INTERVAL_SECONDS
    
    def get_reconnect_config(self) -> tuple[int, int, int]:
        """Get reconnection configuration as (max_attempts, base_delay, max_delay)."""
        return self.MAX_RECONNECT_ATTEMPTS, self.RECONNECT_BASE_DELAY_SECONDS, self.RECONNECT_MAX_DELAY_SECONDS
    
    def get_fastapi_config(self) -> tuple[str, int]:
        """Get FastAPI server configuration as (host, port)."""
        return self.FASTAPI_HOST, self.FASTAPI_PORT

# Global configuration instance
config = Config() 