"""
Twitch EventSub WebSocket Client

This module provides a comprehensive client for interacting with the Twitch EventSub WebSocket API.
It handles OAuth authentication, WebSocket connections, event subscriptions, and automatic reconnection.

Key features:
- OAuth 2.0 Authorization Code Grant flow
- WebSocket connection with automatic reconnection
- Event subscription management
- Comprehensive error handling and logging
- Token refresh and validation
"""

import asyncio
import json
import logging
import time
import secrets
import urllib.parse
from typing import Dict, Any, Optional, Callable, List, Tuple
import websockets
import aiohttp
from websockets.exceptions import ConnectionClosed, WebSocketException

# Configure logging
logger = logging.getLogger(__name__)

class TwitchAPIError(Exception):
    """Raised when Twitch API returns an error."""
    pass

class TwitchAuthenticationError(Exception):
    """Raised when authentication fails."""
    pass

class TwitchConnectionError(Exception):
    """Raised when WebSocket connection fails."""
    pass

class TwitchEventSub:
    """
    A comprehensive client for Twitch EventSub WebSocket connections and events.
    
    This client handles OAuth authentication, WebSocket connections, event subscriptions,
    and provides automatic reconnection capabilities.
    
    Attributes:
        client_id: Twitch application client ID
        client_secret: Twitch application client secret
        redirect_uri: OAuth redirect URI
        access_token: Current access token
        refresh_token: Current refresh token
        token_type: Type of token ("app" or "user")
        session_id: Current WebSocket session ID
        is_connected: Whether the WebSocket is currently connected
    """
    
    # API endpoints
    TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
    TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
    TWITCH_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
    TWITCH_REVOKE_URL = "https://id.twitch.tv/oauth2/revoke"
    TWITCH_API_BASE_URL = "https://api.twitch.tv/helix"
    TWITCH_EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"
    
    # OAuth state expiration time (5 minutes)
    OAUTH_STATE_EXPIRY = 300
    
    # WebSocket keepalive timeout
    DEFAULT_KEEPALIVE_TIMEOUT = 10
    
    def __init__(self, client_id: str, client_secret: str, redirect_uri: Optional[str] = None):
        """
        Initialize the Twitch EventSub client.
        
        Args:
            client_id: Twitch application client ID
            client_secret: Twitch application client secret
            redirect_uri: OAuth redirect URI (defaults to localhost)
        
        Raises:
            ValueError: If client_id or client_secret is empty
        """
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret are required")
        
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri or "http://localhost:8000/callback"
        
        # Token storage
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_type: str = "app"
        self.token_expires_at: Optional[float] = None
        self.scopes: List[str] = []
        
        # OAuth state management
        self.oauth_states: Dict[str, Dict[str, Any]] = {}
        
        # WebSocket connection
        self.session_id: Optional[str] = None
        self.websocket: Optional[Any] = None
        self.keepalive_timeout: int = self.DEFAULT_KEEPALIVE_TIMEOUT
        self.reconnect_url: Optional[str] = None
        self.is_connected: bool = False
        self.is_reconnecting: bool = False
        
        # Event callbacks
        self.event_callbacks: Dict[str, List[Callable]] = {}
        
        logger.info(f"TwitchEventSub client initialized for client_id: {client_id}")

    def generate_auth_url(self, scopes: List[str], state: Optional[str] = None) -> str:
        """
        Generate an authorization URL for the OAuth Authorization Code Grant flow.
        
        Args:
            scopes: List of permission scopes to request
            state: Optional state parameter for security (auto-generated if not provided)
            
        Returns:
            The authorization URL to redirect users to
            
        Raises:
            ValueError: If scopes list is empty
        """
        if not scopes:
            raise ValueError("At least one scope is required")
        
        if not state:
            state = secrets.token_urlsafe(32)
        
        # Store state for validation
        self.oauth_states[state] = {
            "scopes": scopes,
            "timestamp": time.time()
        }
        
        # Clean up old states
        self._cleanup_expired_states()
        
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state
        }
        
        query_string = urllib.parse.urlencode(params)
        auth_url = f"{self.TWITCH_AUTH_URL}?{query_string}"
        
        logger.info(f"Generated auth URL with scopes: {scopes}")
        return auth_url
    
    def _cleanup_expired_states(self) -> None:
        """Clean up expired OAuth states."""
        current_time = time.time()
        expired_states = [
            state for state, data in self.oauth_states.items()
            if current_time - data["timestamp"] > self.OAUTH_STATE_EXPIRY
        ]
        
        for state in expired_states:
            del self.oauth_states[state]
        
        if expired_states:
            logger.debug(f"Cleaned up {len(expired_states)} expired OAuth states")
    
    async def exchange_code_for_token(self, code: str, state: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access token using OAuth Authorization Code Grant flow.
        
        Args:
            code: The authorization code received from the callback
            state: The state parameter to validate
            
        Returns:
            Token response containing access_token, refresh_token, etc.
            
        Raises:
            TwitchAuthenticationError: If authentication fails
            ValueError: If state is invalid or expired
        """
        # Validate state
        if state not in self.oauth_states:
            raise ValueError("Invalid state parameter")
        
        oauth_data = self.oauth_states.pop(state)
        
        # Check if state is not expired
        if time.time() - oauth_data["timestamp"] > self.OAUTH_STATE_EXPIRY:
            raise ValueError("State parameter expired")
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.TWITCH_TOKEN_URL, data=data) as response:
                    response_data = await response.json()
                    
                    if response.status == 200:
                        self._store_token_data(response_data)
                        logger.info(f"Successfully obtained user access token with scopes: {self.scopes}")
                        return response_data
                    else:
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"Token exchange failed: {error_msg}")
                        raise TwitchAuthenticationError(f"Failed to exchange code for token: {error_msg}")
        
        except aiohttp.ClientError as e:
            logger.error(f"Network error during token exchange: {e}")
            raise TwitchAuthenticationError(f"Network error during token exchange: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during token exchange: {e}")
            raise TwitchAuthenticationError(f"Unexpected error during token exchange: {e}")
    
    def _store_token_data(self, token_data: Dict[str, Any]) -> None:
        """
        Store token data from API response.
        
        Args:
            token_data: Token response data from Twitch API
        """
        self.access_token = token_data["access_token"]
        self.refresh_token = token_data.get("refresh_token")
        self.token_type = "user"
        self.scopes = token_data.get("scope", [])
        
        # Calculate expiration time
        expires_in = token_data.get("expires_in")
        if expires_in:
            self.token_expires_at = time.time() + expires_in
    
    async def refresh_user_token(self) -> Dict[str, Any]:
        """
        Refresh the user access token using the refresh token.
        
        Returns:
            New token response
            
        Raises:
            TwitchAuthenticationError: If token refresh fails
            ValueError: If no refresh token is available
        """
        if not self.refresh_token:
            raise ValueError("No refresh token available")
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.TWITCH_TOKEN_URL, data=data) as response:
                    response_data = await response.json()
                    
                    if response.status == 200:
                        # Update token information
                        self.access_token = response_data["access_token"]
                        self.refresh_token = response_data.get("refresh_token", self.refresh_token)
                        self.scopes = response_data.get("scope", self.scopes)
                        
                        # Calculate expiration time
                        expires_in = response_data.get("expires_in")
                        if expires_in:
                            self.token_expires_at = time.time() + expires_in
                        
                        logger.info("Successfully refreshed user access token")
                        return response_data
                    else:
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"Token refresh failed: {error_msg}")
                        raise TwitchAuthenticationError(f"Failed to refresh token: {error_msg}")
        
        except aiohttp.ClientError as e:
            logger.error(f"Network error during token refresh: {e}")
            raise TwitchAuthenticationError(f"Network error during token refresh: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during token refresh: {e}")
            raise TwitchAuthenticationError(f"Unexpected error during token refresh: {e}")
    
    async def validate_token(self) -> Dict[str, Any]:
        """
        Validate the current access token.
        
        Returns:
            Token validation response
            
        Raises:
            TwitchAuthenticationError: If token validation fails
            ValueError: If no access token is available
        """
        if not self.access_token:
            raise ValueError("No access token available")
        
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.TWITCH_VALIDATE_URL, headers=headers) as response:
                    response_data = await response.json()
                    
                    if response.status == 200:
                        logger.debug(f"Token is valid. Client ID: {response_data.get('client_id')}")
                        return response_data
                    else:
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"Token validation failed: {error_msg}")
                        raise TwitchAuthenticationError(f"Token validation failed: {error_msg}")
        
        except aiohttp.ClientError as e:
            logger.error(f"Network error during token validation: {e}")
            raise TwitchAuthenticationError(f"Network error during token validation: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during token validation: {e}")
            raise TwitchAuthenticationError(f"Unexpected error during token validation: {e}")
    
    async def revoke_token(self) -> None:
        """
        Revoke the current access token.
        
        Raises:
            TwitchAuthenticationError: If token revocation fails
            ValueError: If no access token is available
        """
        if not self.access_token:
            raise ValueError("No access token available")
        
        data = {
            "client_id": self.client_id,
            "token": self.access_token
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.TWITCH_REVOKE_URL, data=data) as response:
                    if response.status == 200:
                        logger.info("Token revoked successfully")
                        self._clear_token_data()
                    else:
                        response_data = await response.json()
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"Token revocation failed: {error_msg}")
                        raise TwitchAuthenticationError(f"Failed to revoke token: {error_msg}")
        
        except aiohttp.ClientError as e:
            logger.error(f"Network error during token revocation: {e}")
            raise TwitchAuthenticationError(f"Network error during token revocation: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during token revocation: {e}")
            raise TwitchAuthenticationError(f"Unexpected error during token revocation: {e}")
    
    def _clear_token_data(self) -> None:
        """Clear all token data."""
        self.access_token = None
        self.refresh_token = None
        self.token_type = "app"
        self.token_expires_at = None
        self.scopes = []
    
    async def ensure_valid_token(self) -> None:
        """
        Ensure we have a valid user access token, refreshing if necessary.
        
        Raises:
            TwitchAuthenticationError: If no valid user token can be obtained
        """
        if not self.access_token:
            raise TwitchAuthenticationError("No user access token available. Please authenticate with Twitch first.")
        
        # Check if token is expired (refresh 1 minute before expiration)
        if self.token_expires_at and time.time() >= self.token_expires_at - 60:
            if self.refresh_token and self.token_type == "user":
                try:
                    await self.refresh_user_token()
                    return
                except TwitchAuthenticationError:
                    logger.error("Failed to refresh user token")
                    raise TwitchAuthenticationError("Failed to refresh user access token. Please re-authenticate.")
            else:
                raise TwitchAuthenticationError("Token expired and no refresh token available. Please re-authenticate.")
        
        # Validate current token
        try:
            await self.validate_token()
        except TwitchAuthenticationError:
            logger.error("Token validation failed")
            raise TwitchAuthenticationError("Token validation failed. Please re-authenticate.")
    
    def get_required_scopes_for_subscription(self, subscription_type: str) -> List[str]:
        """
        Get the required scopes for a specific EventSub subscription type.
        
        Args:
            subscription_type: The type of EventSub subscription
            
        Returns:
            List of required scopes
        """
        scope_mapping = {
            "channel.follow": ["moderator:read:followers"],
            "channel.subscribe": ["channel:read:subscriptions"],
            "channel.subscription.gift": ["channel:read:subscriptions"],
            "channel.subscription.message": ["channel:read:subscriptions"],
            "channel.cheer": ["bits:read"],
            "channel.raid": ["channel:read:raids"],
            "channel.poll.begin": ["channel:read:polls"],
            "channel.poll.progress": ["channel:read:polls"],
            "channel.poll.end": ["channel:read:polls"],
            "channel.prediction.begin": ["channel:read:predictions"],
            "channel.prediction.progress": ["channel:read:predictions"],
            "channel.prediction.lock": ["channel:read:predictions"],
            "channel.prediction.end": ["channel:read:predictions"],
            "channel.hype_train.begin": ["channel:read:hype_train"],
            "channel.hype_train.progress": ["channel:read:hype_train"],
            "channel.hype_train.end": ["channel:read:hype_train"],
            "channel.goal.begin": ["channel:read:goals"],
            "channel.goal.progress": ["channel:read:goals"],
            "channel.goal.end": ["channel:read:goals"],
            "channel.charity_campaign.donate": ["channel:read:charity"],
            "channel.charity_campaign.start": ["channel:read:charity"],
            "channel.charity_campaign.progress": ["channel:read:charity"],
            "channel.charity_campaign.stop": ["channel:read:charity"],
            "drop.entitlement.grant": ["channel:read:redemptions"],
            "extension.bits_transaction.create": ["bits:read"],
            "channel.channel_points_custom_reward.add": ["channel:read:redemptions"],
            "channel.channel_points_custom_reward.update": ["channel:read:redemptions"],
            "channel.channel_points_custom_reward.remove": ["channel:read:redemptions"],
            "channel.channel_points_custom_reward_redemption.add": ["channel:read:redemptions"],
            "channel.channel_points_custom_reward_redemption.update": ["channel:read:redemptions"],
            "channel.shield_mode.begin": ["moderator:read:shield_mode"],
            "channel.shield_mode.end": ["moderator:read:shield_mode"],
            "channel.shoutout.create": ["moderator:read:shoutouts"],
            "channel.shoutout.receive": ["moderator:read:shoutouts"],
            "stream.online": [],  # No special scopes required
            "stream.offline": [],  # No special scopes required
        }
        
        return scope_mapping.get(subscription_type, [])
    
    async def connect(self) -> None:
        """
        Connect to the Twitch EventSub WebSocket.
        
        Raises:
            TwitchConnectionError: If connection fails
            TwitchAuthenticationError: If token validation fails
        """
        try:
            await self.ensure_valid_token()
            
            # Use reconnect URL if available, otherwise use default URL
            url = self.reconnect_url if self.reconnect_url else self.TWITCH_EVENTSUB_WS_URL
            
            logger.info(f"Connecting to Twitch EventSub WebSocket: {url}")
            self.websocket = await websockets.connect(url)
            self.is_connected = True
            
            # Start message handling
            await self._handle_messages()
            
        except TwitchAuthenticationError:
            logger.error("Authentication failed during connection")
            raise
        except websockets.exceptions.WebSocketException as e:
            logger.error(f"WebSocket connection failed: {e}")
            self.is_connected = False
            raise TwitchConnectionError(f"Failed to connect to Twitch EventSub: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during connection: {e}")
            self.is_connected = False
            raise TwitchConnectionError(f"Unexpected error during connection: {e}")
    
    async def _handle_messages(self) -> None:
        """
        Handle incoming WebSocket messages.
        
        This method runs in a loop, processing messages until the connection is closed.
        """
        try:
            if self.websocket is None:
                logger.error("WebSocket is None")
                return
            
            async for message in self.websocket:
                await self._process_message(message)
                
        except ConnectionClosed:
            logger.info("WebSocket connection closed")
            self.is_connected = False
        except WebSocketException as e:
            logger.error(f"WebSocket error: {e}")
            self.is_connected = False
        except Exception as e:
            logger.error(f"Error handling messages: {e}")
            self.is_connected = False
    
    async def _process_message(self, message: Any) -> None:
        """
        Process individual WebSocket messages based on their type.
        
        Args:
            message: The WebSocket message to process
        """
        try:
            # Handle both str and bytes message types
            if isinstance(message, bytes):
                message_str = message.decode('utf-8')
            else:
                message_str = str(message)
            
            data = json.loads(message_str)
            metadata = data.get("metadata", {})
            message_type = metadata.get("message_type")
            
            logger.debug(f"Received message type: {message_type}")
            
            # Route message to appropriate handler
            if message_type == "session_welcome":
                await self._handle_welcome_message(data)
            elif message_type == "session_keepalive":
                await self._handle_keepalive_message(data)
            elif message_type == "notification":
                await self._handle_notification_message(data)
            elif message_type == "session_reconnect":
                await self._handle_reconnect_message(data)
            elif message_type == "revocation":
                await self._handle_revocation_message(data)
            else:
                logger.warning(f"Unknown message type: {message_type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON message: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    async def _handle_welcome_message(self, data: Dict[str, Any]) -> None:
        """
        Handle the welcome message and extract session information.
        
        Args:
            data: Welcome message data
        """
        try:
            payload = data.get("payload", {})
            session = payload.get("session", {})
            
            self.session_id = session.get("id")
            self.keepalive_timeout = session.get("keepalive_timeout_seconds", self.DEFAULT_KEEPALIVE_TIMEOUT)
            
            logger.info(f"Connected to EventSub with session ID: {self.session_id}")
            logger.info(f"Keepalive timeout: {self.keepalive_timeout} seconds")
            
            # Trigger welcome callback
            await self._trigger_callback("welcome", data)
            
        except Exception as e:
            logger.error(f"Error handling welcome message: {e}")
    
    async def _handle_keepalive_message(self, data: Dict[str, Any]) -> None:
        """
        Handle keepalive messages.
        
        Args:
            data: Keepalive message data
        """
        logger.debug("Received keepalive message")
        await self._trigger_callback("keepalive", data)
    
    async def _handle_notification_message(self, data: Dict[str, Any]) -> None:
        """
        Handle notification messages (actual events).
        
        Args:
            data: Notification message data
        """
        try:
            metadata = data.get("metadata", {})
            subscription_type = metadata.get("subscription_type")
            
            payload = data.get("payload", {})
            event_data = payload.get("event", {})
            
            logger.info(f"Received event: {subscription_type}")
            
            # Trigger specific event callback
            await self._trigger_callback(subscription_type, event_data)
            
            # Trigger general notification callback
            await self._trigger_callback("notification", data)
            
        except Exception as e:
            logger.error(f"Error handling notification message: {e}")
    
    async def _handle_reconnect_message(self, data: Dict[str, Any]) -> None:
        """
        Handle reconnect messages.
        
        Args:
            data: Reconnect message data
        """
        try:
            payload = data.get("payload", {})
            session = payload.get("session", {})
            
            self.reconnect_url = session.get("reconnect_url")
            
            logger.info(f"Received reconnect message. New URL: {self.reconnect_url}")
            
            # Start reconnection process
            self.is_reconnecting = True
            await self._trigger_callback("reconnect", data)
            
            # Initiate reconnection
            asyncio.create_task(self._reconnect())
            
        except Exception as e:
            logger.error(f"Error handling reconnect message: {e}")
    
    async def _handle_revocation_message(self, data: Dict[str, Any]) -> None:
        """
        Handle revocation messages.
        
        Args:
            data: Revocation message data
        """
        try:
            payload = data.get("payload", {})
            subscription = payload.get("subscription", {})
            
            logger.warning(f"Subscription revoked: {subscription}")
            await self._trigger_callback("revocation", data)
            
        except Exception as e:
            logger.error(f"Error handling revocation message: {e}")
    
    async def _reconnect(self) -> None:
        """
        Handle reconnection logic.
        
        This method attempts to establish a new connection using the reconnect URL.
        """
        if not self.reconnect_url:
            logger.error("No reconnect URL available")
            return
        
        try:
            logger.info("Attempting to reconnect to EventSub")
            
            # Create new connection
            new_websocket = await websockets.connect(self.reconnect_url)
            
            # Wait for welcome message on new connection
            welcome_message = await new_websocket.recv()
            await self._process_message(welcome_message)
            
            # Close old connection
            if self.websocket:
                await self.websocket.close()
            
            # Update to new connection
            self.websocket = new_websocket
            self.is_reconnecting = False
            self.reconnect_url = None
            
            logger.info("Successfully reconnected to EventSub")
            
            # Continue handling messages on new connection
            await self._handle_messages()
            
        except Exception as e:
            logger.error(f"Failed to reconnect: {e}")
            self.is_reconnecting = False
    
    async def _trigger_callback(self, event_type: str, data: Any) -> None:
        """
        Trigger callbacks for specific event types.
        
        Args:
            event_type: The type of event
            data: The event data
        """
        if event_type in self.event_callbacks:
            for callback in self.event_callbacks[event_type]:
                try:
                    await callback(data)
                except Exception as e:
                    logger.error(f"Error in callback for {event_type}: {e}")
    
    def add_event_callback(self, event_type: str, callback: Callable) -> None:
        """
        Add a callback for a specific event type.
        
        Args:
            event_type: The type of event to listen for
            callback: The callback function to call when the event occurs
        """
        if event_type not in self.event_callbacks:
            self.event_callbacks[event_type] = []
        self.event_callbacks[event_type].append(callback)
        logger.debug(f"Added callback for event type: {event_type}")
    
    async def subscribe_to_event(self, subscription_type: str, condition: Dict[str, Any]) -> bool:
        """
        Subscribe to a specific event type.
        
        Args:
            subscription_type: The type of event to subscribe to
            condition: The condition parameters for the subscription
            
        Returns:
            True if subscription was successful, False otherwise
            
        Raises:
            TwitchAuthenticationError: If authentication fails
        """
        if not self.session_id:
            logger.error("No session ID available. Make sure to connect first.")
            return False
        
        try:
            await self.ensure_valid_token()
            
            # Check if we have required scopes for this subscription type
            required_scopes = self.get_required_scopes_for_subscription(subscription_type)
            if required_scopes and self.token_type == "user":
                missing_scopes = [scope for scope in required_scopes if scope not in self.scopes]
                if missing_scopes:
                    logger.error(f"Missing required scopes for {subscription_type}: {missing_scopes}")
                    return False
            
            url = f"{self.TWITCH_API_BASE_URL}/eventsub/subscriptions"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Client-Id": self.client_id,
                "Content-Type": "application/json"
            }
            
            data = {
                "type": subscription_type,
                "version": "1",
                "condition": condition,
                "transport": {
                    "method": "websocket",
                    "session_id": self.session_id
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as response:
                    response_data = await response.json()
                    
                    if response.status == 202:
                        logger.info(f"Successfully subscribed to {subscription_type}")
                        return True
                    else:
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"Failed to subscribe to {subscription_type}: {error_msg}")
                        return False
        
        except TwitchAuthenticationError:
            logger.error(f"Authentication failed while subscribing to {subscription_type}")
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Network error while subscribing to {subscription_type}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while subscribing to {subscription_type}: {e}")
            return False
    
    async def get_subscriptions(self) -> List[Dict[str, Any]]:
        """
        Get all current subscriptions.
        
        Returns:
            List of subscription data
            
        Raises:
            TwitchAuthenticationError: If authentication fails
        """
        try:
            await self.ensure_valid_token()
            
            url = f"{self.TWITCH_API_BASE_URL}/eventsub/subscriptions"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Client-Id": self.client_id
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    response_data = await response.json()
                    
                    if response.status == 200:
                        return response_data.get("data", [])
                    else:
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"Failed to get subscriptions: {error_msg}")
                        return []
        
        except TwitchAuthenticationError:
            logger.error("Authentication failed while getting subscriptions")
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Network error while getting subscriptions: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error while getting subscriptions: {e}")
            return []
    
    async def get_user_id_by_username(self, username: str) -> Optional[str]:
        """
        Get user ID by username.
        
        Args:
            username: The username to look up
            
        Returns:
            User ID if found, None otherwise
            
        Raises:
            TwitchAuthenticationError: If authentication fails
            ValueError: If username is empty
        """
        if not username:
            raise ValueError("Username cannot be empty")
        
        try:
            await self.ensure_valid_token()
            
            url = f"{self.TWITCH_API_BASE_URL}/users?login={username}"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Client-Id": self.client_id
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    response_data = await response.json()
                    
                    if response.status == 200:
                        users = response_data.get("data", [])
                        if users:
                            return users[0]["id"]
                        else:
                            logger.warning(f"User '{username}' not found")
                            return None
                    else:
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"Failed to get user ID for '{username}': {error_msg}")
                        return None
        
        except TwitchAuthenticationError:
            logger.error(f"Authentication failed while getting user ID for '{username}'")
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Network error while getting user ID for '{username}': {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error while getting user ID for '{username}': {e}")
            return None
    
    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get basic user information (including profile image) for a given user ID.
        
        Args:
            user_id: The user ID to get information for
            
        Returns:
            User information if found, None otherwise
            
        Raises:
            TwitchAuthenticationError: If authentication fails
            ValueError: If user_id is empty
        """
        if not user_id:
            raise ValueError("User ID cannot be empty")
        
        try:
            await self.ensure_valid_token()
            
            url = f"{self.TWITCH_API_BASE_URL}/users?id={user_id}"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Client-Id": self.client_id
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    response_data = await response.json()
                    
                    if response.status == 200:
                        users = response_data.get("data", [])
                        if users:
                            return users[0]
                        else:
                            logger.warning(f"User with ID '{user_id}' not found")
                            return None
                    else:
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"Failed to get user info for ID '{user_id}': {error_msg}")
                        return None
        
        except TwitchAuthenticationError:
            logger.error(f"Authentication failed while getting user info for ID '{user_id}'")
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Network error while getting user info for ID '{user_id}': {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error while getting user info for ID '{user_id}': {e}")
            return None
    
    async def get_stream_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed stream information for a user.
        
        Args:
            user_id: The user ID to get stream info for
            
        Returns:
            Stream information if the user is live, None otherwise
            
        Raises:
            TwitchAuthenticationError: If authentication fails
            ValueError: If user_id is empty
        """
        if not user_id:
            raise ValueError("User ID cannot be empty")
        
        try:
            await self.ensure_valid_token()
            
            url = f"{self.TWITCH_API_BASE_URL}/streams?user_id={user_id}"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Client-Id": self.client_id
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    response_data = await response.json()
                    
                    if response.status == 200:
                        streams = response_data.get("data", [])
                        if streams:
                            return streams[0]
                        else:
                            logger.debug(f"User with ID '{user_id}' is not currently live")
                            return None
                    else:
                        error_msg = response_data.get("message", "Unknown error")
                        logger.error(f"Failed to get stream info for user ID '{user_id}': {error_msg}")
                        return None
        
        except TwitchAuthenticationError:
            logger.error(f"Authentication failed while getting stream info for user ID '{user_id}'")
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Network error while getting stream info for user ID '{user_id}': {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error while getting stream info for user ID '{user_id}': {e}")
            return None
    
    async def disconnect(self) -> None:
        """
        Disconnect from the WebSocket.
        
        This method cleanly closes the WebSocket connection.
        """
        if self.websocket:
            try:
                await self.websocket.close()
                logger.info("Disconnected from Twitch EventSub")
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
            finally:
                self.is_connected = False
                self.websocket = None
    
    async def run(self) -> None:
        """
        Run the EventSub client with automatic reconnection.
        
        This method handles the main connection loop with exponential backoff
        for reconnection attempts.
        """
        reconnect_attempts = 0
        max_reconnect_attempts = 5
        base_delay = 1  # Start with 1 second delay
        max_delay = 60  # Maximum delay of 60 seconds
        
        while True:
            try:
                await self.connect()
                # Reset reconnection attempts on successful connection
                reconnect_attempts = 0
                
            except (TwitchConnectionError, TwitchAuthenticationError) as e:
                logger.error(f"Connection failed: {e}")
                
                # Implement exponential backoff for persistent failures
                if reconnect_attempts < max_reconnect_attempts:
                    delay = min(base_delay * (2 ** reconnect_attempts), max_delay)
                    logger.info(f"Reconnecting in {delay} seconds... (attempt {reconnect_attempts + 1}/{max_reconnect_attempts})")
                    await asyncio.sleep(delay)
                    reconnect_attempts += 1
                else:
                    # After max attempts, wait longer before trying again
                    logger.info("Max reconnection attempts reached. Waiting 60 seconds before trying again...")
                    await asyncio.sleep(60)
                    reconnect_attempts = 0  # Reset attempts after long wait
                    
            except Exception as e:
                logger.error(f"Unexpected error in run loop: {e}")
                await asyncio.sleep(5)  # Short delay for unexpected errors
