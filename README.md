# Twitch Discord Bot

A production-ready Discord bot that monitors Twitch streams and sends notifications when streamers go live. This bot uses the Twitch EventSub WebSocket API for real-time notifications and includes robust error handling, automatic reconnection, and comprehensive logging.

## Features

- **Real-time Stream Notifications**: Get instant Discord notifications when a streamer goes live
- **OAuth 2.0 Authentication**: Secure authentication with Twitch using OAuth 2.0 Authorization Code Grant flow
- **Automatic Reconnection**: Robust WebSocket connection management with exponential backoff
- **Health Monitoring**: Built-in health check and status endpoints for monitoring
- **Comprehensive Logging**: Detailed logging with multiple levels for debugging and monitoring
- **Production Ready**: Proper error handling, configuration management, and security practices

## Prerequisites

- Python 3.8 or higher
- A Discord bot token
- A Twitch application with Client ID and Client Secret

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd twitch-discord-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp env.example .env
```

4. Edit the `.env` file with your configuration:
```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
TWITCH_CLIENT_ID=your_twitch_client_id_here
TWITCH_CLIENT_SECRET=your_twitch_client_secret_here
TWITCH_USERNAME=streamer_username_to_monitor
STREAM_NOTIFICATION_CHANNEL_ID=your_discord_channel_id_here
```

## Configuration

### Required Environment Variables

- `DISCORD_BOT_TOKEN`: Your Discord bot token
- `TWITCH_CLIENT_ID`: Your Twitch application client ID
- `TWITCH_CLIENT_SECRET`: Your Twitch application client secret
- `TWITCH_USERNAME`: The Twitch username to monitor for live notifications

### Optional Environment Variables

- `REDIRECT_URI`: OAuth redirect URI (default: `http://localhost/callback`)
- `STREAM_NOTIFICATION_CHANNEL_ID`: Discord channel ID for notifications (falls back to common channel names)

## Setup Instructions

### 1. Discord Bot Setup

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to the "Bot" section
4. Create a bot and copy the token
5. Enable the following bot permissions:
   - Send Messages
   - Use Slash Commands
   - Embed Links
   - Read Message History
   - View Channels

### 2. Twitch Application Setup

1. Go to the [Twitch Developer Console](https://dev.twitch.tv/console)
2. Create a new application
3. Set the OAuth Redirect URL to `http://localhost/callback` (or your custom domain)
4. Copy the Client ID and Client Secret

### 3. Running the Bot

1. Start the bot:
```bash
python src/main.py
```

2. The bot will automatically:
   - Start a web server for OAuth callbacks
   - Open your browser for Twitch authentication
   - Connect to Discord
   - Subscribe to the configured streamer's events

## API Endpoints

The bot includes several HTTP endpoints for monitoring:

- `GET /health` - Health check endpoint
- `GET /status` - Detailed bot status information
- `GET /callback` - OAuth callback endpoint (used internally)

## Project Structure

```
src/
├── main.py          # Main application entry point
├── config.py        # Configuration management
├── twitch.py        # Twitch EventSub client
└── templates/       # HTML templates for OAuth pages
    ├── oauth_success.html
    ├── oauth_error.html
    └── oauth_missing_params.html
```

## Architecture

The bot consists of three main components:

1. **Discord Bot**: Handles Discord connections and message sending
2. **Twitch EventSub Client**: Manages WebSocket connections to Twitch EventSub API
3. **FastAPI Server**: Handles OAuth callbacks and provides monitoring endpoints

## Error Handling

The bot includes comprehensive error handling:

- **Authentication Errors**: Automatic token refresh and re-authentication prompts
- **Connection Errors**: Exponential backoff reconnection strategy
- **API Errors**: Proper error logging and graceful degradation
- **Configuration Errors**: Validation at startup with clear error messages

## Logging

The bot uses Python's built-in logging module with:

- Console output for immediate feedback
- File logging (`bot.log`) for persistent logs
- Different log levels (DEBUG, INFO, WARNING, ERROR)
- Structured logging for better troubleshooting

## Security Considerations

- OAuth state validation prevents CSRF attacks
- Environment variables for sensitive configuration
- Token refresh handling for long-running processes
- Input validation and sanitization

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support, please check the following:

1. Review the logs in `bot.log`
2. Check the `/status` endpoint for bot state
3. Verify your environment variables are correct
4. Ensure your Discord bot has the necessary permissions

## Troubleshooting

### Common Issues

1. **Bot doesn't connect to Discord**: Check your Discord bot token
2. **OAuth authentication fails**: Verify your Twitch client ID and secret
3. **No stream notifications**: Ensure the streamer username is correct
4. **Permission errors**: Check Discord bot permissions in your server

### Debug Mode

To enable debug logging, modify the logging configuration in `config.py`:

```python
logging.basicConfig(level=logging.DEBUG, ...)
```