"""
Twitch Discord Bot - Main Application

A Discord bot that monitors Twitch streams and sends notifications when streamers go live.
This bot uses Twitch EventSub WebSocket API to receive real-time notifications.
"""

import asyncio
import logging
import threading
from datetime import datetime
from typing import Optional
import os

import discord
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn

from config import config, ConfigurationError
from twitch import TwitchEventSub

# Configure logging
logger = logging.getLogger(__name__)

# Initialize Discord client
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)

# Initialize Twitch EventSub client
twitch_client = TwitchEventSub(
    client_id=config.TWITCH_CLIENT_ID,
    client_secret=config.TWITCH_CLIENT_SECRET,
    redirect_uri=config.REDIRECT_URI
)

# Initialize FastAPI app
app = FastAPI(title="Twitch OAuth Handler", version="1.0.0")


class HTMLTemplateLoader:
    """Handles loading and rendering HTML templates."""
    
    @staticmethod
    def load_template(template_name: str, **kwargs) -> str:
        """
        Load HTML template with optional variable substitution.
        
        Args:
            template_name: Name of the template file
            **kwargs: Variables to substitute in the template
            
        Returns:
            Rendered HTML content
        """
        template_path = f"src/templates/{template_name}"
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Simple template variable substitution
            for key, value in kwargs.items():
                content = content.replace(f'{{{{{key}}}}}', str(value))
            
            return content
        except FileNotFoundError:
            logger.error(f"Template {template_name} not found")
            return f"<html><body><h1>Template {template_name} not found</h1></body></html>"
        except Exception as e:
            logger.error(f"Error loading template {template_name}: {e}")
            return f"<html><body><h1>Error loading template</h1></body></html>"


class DiscordNotificationService:
    """Handles Discord notifications and channel management."""
    
    @staticmethod
    def get_welcome_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
        """
        Get the Discord channel for welcome messages.
        
        Args:
            guild: The Discord guild where the member joined
            
        Returns:
            The welcome channel or None if not found
        """
        # Try to get specific channel by ID
        if config.DISCORD_WELCOME_CHANNEL_ID:
            try:
                channel = guild.get_channel(int(config.DISCORD_WELCOME_CHANNEL_ID))
                if channel and isinstance(channel, discord.TextChannel):
                    return channel
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid welcome channel ID in configuration: {e}")
        
        # Fallback to guild's system channel
        return guild.system_channel
    
    @staticmethod
    def get_notification_channel() -> Optional[discord.TextChannel]:
        """
        Get the Discord channel for notifications.
        
        Returns:
            The notification channel or None if not found
        """
        # Try to get specific channel by ID
        if config.STREAM_NOTIFICATION_CHANNEL_ID:
            try:
                channel = client.get_channel(int(config.STREAM_NOTIFICATION_CHANNEL_ID))
                if channel and isinstance(channel, discord.TextChannel):
                    return channel
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid channel ID in configuration: {e}")
        
        # Fallback to common channel names
        for guild in client.guilds:
            for channel in guild.text_channels:
                if channel.name in ["general", "stream-notifications", "bot-commands"]:
                    return channel
        
        logger.warning("No suitable notification channel found")
        return None
    
    @staticmethod
    async def send_stream_notification(
        broadcaster_name: str,
        title: str,
        game: str,
        stream_info: Optional[dict] = None,
        user_info: Optional[dict] = None,
        started_at_iso: str = ""
    ) -> None:
        """
        Send stream notification to Discord channel.
        
        Args:
            broadcaster_name: Name of the broadcaster
            title: Stream title
            game: Game/category being streamed
            stream_info: Optional stream information
            user_info: Optional user information
            started_at_iso: ISO timestamp of stream start
        """
        try:
            channel = DiscordNotificationService.get_notification_channel()
            if not channel:
                logger.error("No notification channel available")
                return
            
            # Create embed
            embed = discord.Embed(
                title=title,
                color=config.DISCORD_EMBED_COLOR,
                url=config.get_twitch_stream_url(broadcaster_name)
            )
            
            # Add author with profile image
            if user_info and user_info.get("profile_image_url"):
                embed.set_author(name=broadcaster_name, icon_url=user_info["profile_image_url"])
            
            # Add stream details
            embed.add_field(name="Category", value=game, inline=True)
            
            # Format start time
            started_value = "Unknown"
            if started_at_iso:
                try:
                    dt = datetime.fromisoformat(started_at_iso.replace('Z', '+00:00'))
                    ts = int(dt.timestamp())
                    started_value = f"<t:{ts}:R>"
                except Exception as e:
                    logger.warning(f"Error parsing stream start time: {e}")
                    started_value = started_at_iso
            
            embed.add_field(name="Started", value=started_value, inline=True)
            
            # Add thumbnail if available
            if stream_info and stream_info.get("thumbnail_url"):
                thumbnail_url = stream_info["thumbnail_url"].replace("{width}", "320").replace("{height}", "180")
                embed.set_image(url=thumbnail_url)
            
            # Add watch link
            embed.add_field(
                name="🔗 Watch Now",
                value=f"[Click here to watch]({config.get_twitch_stream_url(broadcaster_name)})",
                inline=False
            )
            
            embed.set_footer(text=config.DISCORD_EMBED_FOOTER)
            
            # Send notification with optional role ping
            if config.STREAM_NOTIFICATION_ROLE_ID:
                try:
                    role_id = int(config.STREAM_NOTIFICATION_ROLE_ID)
                    content = f"# <@&{role_id}> {broadcaster_name} is LIVE!"
                except (ValueError, TypeError):
                    logger.warning(f"Invalid role ID in configuration: {config.STREAM_NOTIFICATION_ROLE_ID}")
                    content = f"# {broadcaster_name} is LIVE!"
            else:
                content = f"# {broadcaster_name} is LIVE!"
            
            await channel.send(content=content, embed=embed)
            
            logger.info(f"Stream notification sent for {broadcaster_name}")
            
        except Exception as e:
            logger.error(f"Error sending stream notification: {e}")


class OAuthHandler:
    """Handles OAuth authentication flow."""
    
    @staticmethod
    async def initiate_oauth_flow() -> None:
        """
        Initiate the OAuth authentication flow.
        
        This method generates an auth URL, displays it to the user,
        and waits for the user to complete authentication.
        """
        try:
            logger.info("Initiating Twitch OAuth authentication")
            
            # Generate authorization URL
            auth_url = twitch_client.generate_auth_url(config.REQUIRED_TWITCH_SCOPES)
            
            logger.info(f"Authorization URL generated: {auth_url}")
            print(f"\n{'='*60}")
            print(f"AUTHORIZATION REQUIRED")
            print(f"{'='*60}")
            print(f"Please open the following URL in your browser to authorize the bot:")
            print(f"\n{auth_url}")
            print(f"\nAfter authorization, return to this terminal.")
            print(f"{'='*60}\n")
            
            # Wait for OAuth completion
            await OAuthHandler._wait_for_oauth_completion()
            
            logger.info("OAuth authentication completed successfully")
            
            # Start Twitch EventSub connection
            asyncio.create_task(TwitchEventSubService.start_eventsub_connection())
            
        except Exception as e:
            logger.error(f"OAuth authentication failed: {e}")
            # Retry after delay
            await asyncio.sleep(10)
            await OAuthHandler.initiate_oauth_flow()
    
    @staticmethod
    async def _wait_for_oauth_completion() -> None:
        """
        Wait for OAuth completion by polling token status.
        
        Raises:
            TimeoutError: If OAuth doesn't complete within the timeout period
        """
        max_wait, poll_interval = config.get_oauth_timeout_info()
        
        for _ in range(max_wait // poll_interval):
            if twitch_client.access_token and twitch_client.token_type == "user":
                return
            await asyncio.sleep(poll_interval)
        
        logger.warning("OAuth authentication timed out, retrying...")
        await OAuthHandler.initiate_oauth_flow()


class TwitchEventSubService:
    """Handles Twitch EventSub connection and event processing."""
    
    @staticmethod
    async def start_eventsub_connection() -> None:
        """
        Start the Twitch EventSub connection.
        
        This method sets up event callbacks and starts the WebSocket connection.
        """
        try:
            logger.info("Starting Twitch EventSub connection")
            
            # Register event callbacks
            twitch_client.add_event_callback("welcome", TwitchEventSubService._on_welcome)
            twitch_client.add_event_callback("stream.online", TwitchEventSubService._on_stream_online)
            
            # Start the connection
            await twitch_client.run()
            
        except Exception as e:
            logger.error(f"EventSub connection error: {e}")
    
    @staticmethod
    async def _on_welcome(data: dict) -> None:
        """
        Handle Twitch EventSub welcome event.
        
        Args:
            data: Welcome event data
        """
        logger.info("Connected to Twitch EventSub")
        await asyncio.sleep(1)  # Brief delay before subscribing
        await TwitchEventSubService._subscribe_to_stream_events()
    
    @staticmethod
    async def _subscribe_to_stream_events() -> None:
        """Subscribe to stream online events for the configured streamer."""
        try:
            if not twitch_client.session_id or not twitch_client.access_token:
                logger.error("Missing session ID or access token")
                return
            
            # Get user ID for the configured username
            user_id = await twitch_client.get_user_id_by_username(config.TWITCH_USERNAME)
            if not user_id:
                logger.error(f"User '{config.TWITCH_USERNAME}' not found")
                return
            
            # Subscribe to stream online events
            success = await twitch_client.subscribe_to_event(
                "stream.online",
                {"broadcaster_user_id": user_id}
            )
            
            if success:
                logger.info(f"Successfully subscribed to {config.TWITCH_USERNAME}'s stream events")
            else:
                logger.error(f"Failed to subscribe to {config.TWITCH_USERNAME}'s stream events")
                
        except Exception as e:
            logger.error(f"Error subscribing to stream events: {e}")
    
    @staticmethod
    async def _on_stream_online(event_data: dict) -> None:
        """
        Handle stream online events.
        
        Args:
            event_data: Stream online event data
        """
        try:
            broadcaster_name = event_data.get("broadcaster_user_name", "Unknown")
            broadcaster_user_id = event_data.get("broadcaster_user_id")
            
            logger.info(f"{broadcaster_name} is now live!")
            
            # Get additional stream and user information
            stream_info = None
            user_info = None
            stream_title = "No title"
            game_name = "Unknown"
            started_at_iso = ""
            
            if broadcaster_user_id:
                try:
                    stream_info = await twitch_client.get_stream_info(broadcaster_user_id)
                    user_info = await twitch_client.get_user_info(broadcaster_user_id)
                    
                    if stream_info:
                        stream_title = stream_info.get("title", "No title")
                        game_name = stream_info.get("game_name", "Unknown")
                        started_at_iso = stream_info.get("started_at", "")
                        
                except Exception as e:
                    logger.warning(f"Error fetching additional stream info: {e}")
            
            # Send Discord notification
            await DiscordNotificationService.send_stream_notification(
                broadcaster_name=broadcaster_name,
                title=stream_title,
                game=game_name,
                stream_info=stream_info,
                user_info=user_info,
                started_at_iso=started_at_iso
            )
            
        except Exception as e:
            logger.error(f"Error handling stream online event: {e}")


# FastAPI OAuth callback endpoint
@app.get("/callback")
async def oauth_callback(request: Request) -> HTMLResponse:
    """
    Handle OAuth callback from Twitch.
    
    Args:
        request: FastAPI request object
        
    Returns:
        HTML response with success/error page
    """
    try:
        code = request.query_params.get('code')
        state = request.query_params.get('state')
        error = request.query_params.get('error')
        
        if error:
            logger.error(f"OAuth error: {error}")
            return HTMLResponse(HTMLTemplateLoader.load_template("oauth_error.html", error=error))
        
        if not code or not state:
            logger.error("OAuth callback missing required parameters")
            return HTMLResponse(HTMLTemplateLoader.load_template("oauth_missing_params.html"))
        
        # Exchange code for token
        logger.info("Processing OAuth callback")
        await twitch_client.exchange_code_for_token(code, state)
        logger.info("OAuth token exchange successful")
        
        return HTMLResponse(HTMLTemplateLoader.load_template("oauth_success.html"))
        
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        return HTMLResponse(HTMLTemplateLoader.load_template("oauth_error.html", error=str(e)))


@app.get("/health")
async def health_check() -> dict:
    """
    Health check endpoint for monitoring.
    
    Returns:
        Health status information
    """
    return {
        "status": "healthy",
        "service": "twitch-discord-bot",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/status")
async def bot_status() -> dict:
    """
    Bot status endpoint for monitoring bot state.
    
    Returns:
        Bot status information
    """
    return {
        "discord_bot": {
            "connected": client.is_ready(),
            "user": str(client.user) if client.user else None,
            "guilds": len(client.guilds) if client.guilds else 0
        },
        "twitch_eventsub": {
            "connected": twitch_client.is_connected,
            "session_id": twitch_client.session_id,
            "has_token": twitch_client.access_token is not None,
            "token_type": twitch_client.token_type
        },
        "configuration": {
            "twitch_username": config.TWITCH_USERNAME,
            "redirect_uri": config.REDIRECT_URI,
            "notification_channel_configured": config.STREAM_NOTIFICATION_CHANNEL_ID is not None,
            "notification_role_configured": config.STREAM_NOTIFICATION_ROLE_ID is not None
        }
    }


# Discord bot event handlers
@client.event
async def on_ready() -> None:
    """Handle Discord bot ready event."""
    logger.info(f"Discord bot logged in as {client.user}")
    await OAuthHandler.initiate_oauth_flow()


@client.event
async def on_member_join(member: discord.Member) -> None:
    """
    Handle member join event.
    
    Args:
        member: The member who joined
    """
    try:
        welcome_channel = DiscordNotificationService.get_welcome_channel(member.guild)
        if welcome_channel:
            await welcome_channel.send(f'Welcome, {member.mention}! Enjoy the stay!')
        else:
            logger.warning("No welcome channel available")
    except Exception as e:
        logger.error(f"Error sending welcome message: {e}")


def start_fastapi_server() -> None:
    """Start the FastAPI server for OAuth callbacks."""
    host, port = config.get_fastapi_config()
    # Always start HTTP server
    uvicorn.run(app, host=host, port=port, log_level="warning")


def start_fastapi_server_https_if_enabled() -> None:
    """Start the FastAPI HTTPS server on a separate port if enabled and certs are present."""
    host, ssl_port, enabled, certfile, keyfile, keyfile_password = config.get_fastapi_https_config()
    if not enabled:
        return
    # Validate cert files exist before attempting to launch HTTPS
    try:
        if not (os.path.isfile(certfile) and os.path.isfile(keyfile)):
            logger.warning("HTTPS enabled but certificate files not found; skipping HTTPS server")
            return
    except Exception as e:
        logger.warning(f"Error checking cert files: {e}; skipping HTTPS server")
        return

    uvicorn.run(
        app,
        host=host,
        port=ssl_port,
        log_level="warning",
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
        ssl_keyfile_password=keyfile_password,
    )


def main() -> None:
    """
    Main function to run the Discord bot with Twitch EventSub integration.
    
    This function validates configuration, starts the FastAPI server,
    and runs the Discord bot.
    """
    try:
        # Configuration is validated in config.py
        logger.info("Starting Discord bot with Twitch integration")
        
        # Start FastAPI HTTP server in background thread
        server_thread = threading.Thread(target=start_fastapi_server, daemon=True)
        server_thread.start()

        # Start FastAPI HTTPS server in background thread (best-effort)
        https_thread = threading.Thread(target=start_fastapi_server_https_if_enabled, daemon=True)
        https_thread.start()
        
        # Run Discord bot
        client.run(config.DISCORD_BOT_TOKEN)
        
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        return
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return


if __name__ == "__main__":
    main()
