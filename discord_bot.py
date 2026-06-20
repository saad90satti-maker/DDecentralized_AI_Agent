"""
Discord Bot for Ghost Engine

Commands:
  !status       - Show active services and pending tasks
  !execute CMD  - Execute a shell command
  !task CMD     - Queue a task
  !think TEXT   - Send text to Hermes for analysis
  !deploy       - Prepare deployment
  !scale N      - Set max workers
  !help         - Show this help message

Environment variables:
  DISCORD_TOKEN - Bot token
  DISCORD_CHANNEL_ID - Default channel for status reports
  MANAGER_URL - Base URL for Ghost Engine API (default: http://localhost:8000)
"""

import os
import json
import asyncio
import aiohttp
from typing import Optional

try:
    import discord
    from discord.ext import commands
except ImportError:
    discord = None
    commands = None

MANAGER_URL = os.getenv("MANAGER_URL", "http://localhost:8000")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")

class GhostBot(commands.Cog if commands else object):
    def __init__(self, bot=None):
        self.bot = bot
        self.manager_url = MANAGER_URL.rstrip("/")
    
    async def _call_manager(self, endpoint: str, method: str = "GET", payload: Optional[dict] = None) -> dict:
        """Call the Ghost Engine API."""
        url = f"{self.manager_url}{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                if method == "POST":
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as r:
                        return await r.json()
                else:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                        return await r.json()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
    
    async def _format_response(self, data: dict) -> str:
        """Format API response for Discord."""
        if not data:
            return "No response from server."
        
        if data.get("status") == "error":
            return f"❌ Error: {data.get('message', 'Unknown error')}"
        
        # Try to format as a code block if it's complex
        try:
            text = json.dumps(data, indent=2)
            if len(text) > 1900:
                text = text[:1900] + "\n...(truncated)"
            return f"```json\n{text}\n```"
        except:
            return str(data)[:1900]
    
    @commands.command(name="status")
    async def status(self, ctx):
        """Show active services and pending tasks."""
        result = await self._call_manager("/api/status")
        response = await self._format_response(result)
        await ctx.send(response)
    
    @commands.command(name="execute")
    async def execute(self, ctx, *, command: str):
        """Execute a shell command."""
        result = await self._call_manager("/api/execute", "POST", {"command": command, "parallel": False})
        response = await self._format_response(result)
        await ctx.send(response)
    
    @commands.command(name="task")
    async def task(self, ctx, *, command: str):
        """Queue a task for async execution."""
        result = await self._call_manager("/api/task", "POST", {"command": command})
        response = await self._format_response(result)
        await ctx.send(response)
    
    @commands.command(name="think")
    async def think(self, ctx, *, text: str):
        """Send text to Hermes for analysis."""
        result = await self._call_manager("/api/cli", "POST", {"action": "think", "args": [text]})
        response = await self._format_response(result)
        await ctx.send(response)
    
    @commands.command(name="deploy")
    async def deploy(self, ctx):
        """Prepare deployment."""
        result = await self._call_manager("/api/cli", "POST", {"action": "deploy"})
        response = await self._format_response(result)
        await ctx.send(response)
    
    @commands.command(name="scale")
    async def scale(self, ctx, workers: int):
        """Set max parallel workers."""
        result = await self._call_manager("/api/cli", "POST", {"action": "scale", "args": [str(workers)]})
        response = await self._format_response(result)
        await ctx.send(response)
    
    @commands.command(name="help")
    async def help_cmd(self, ctx):
        """Show available commands."""
        await ctx.send(__doc__)

async def main():
    if not discord or not commands:
        print("Error: discord.py library not installed. Install with: pip install discord.py aiohttp")
        return
    
    if not DISCORD_TOKEN:
        print("Error: DISCORD_TOKEN environment variable not set")
        return
    
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)
    
    @bot.event
    async def on_ready():
        print(f"Bot logged in as {bot.user}")
    
    # Add the ghost cog
    await bot.add_cog(GhostBot(bot))
    
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    if not discord:
        print(__doc__)
        print("\nError: discord.py not installed. Install with: pip install discord.py aiohttp")
    else:
        asyncio.run(main())
