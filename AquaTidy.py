import discord
import asyncio
from dotenv import load_dotenv
from discord.ext import tasks, commands
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import logging
from storage import SettingsStore, REMINDERS

# Set up intents
intents = discord.Intents.default()
intents.message_content = True  # Enables access to message content
intents.members = True  # Enables access to member details

load_dotenv()
logger = logging.getLogger(__name__)


class AquaTidyBot(commands.Bot):
    async def setup_hook(self):
        if not hasattr(self, "settings"):
            self.settings = SettingsStore(os.getenv("DATABASE_PATH", "data/aquatidy.sqlite3"))
        for loop in (update_hydrated_roles, update_bottle_check_roles, update_clean_room_roles):
            if not loop.is_running():
                loop.start()

    async def close(self):
        pending = []
        for loop in (update_hydrated_roles, update_bottle_check_roles, update_clean_room_roles):
            task = loop.get_task()
            loop.cancel()
            if task is not None:
                pending.append(task)
        await asyncio.gather(*pending, return_exceptions=True)
        await super().close()
        if hasattr(self, "settings"):
            self.settings.close()
            del self.settings


bot = AquaTidyBot(command_prefix="!", intents=intents)

# Default role map
DEFAULT_ROLE_MAP = {
    "🥤": "Bottle Check",
    "💧": "Hydrated",
    "🧹": "Clean Room"
}

@bot.event
async def on_ready():
    logger.info("%s has connected to Discord!", bot.user)

# Function to create roles based on role_map
async def create_roles(ctx, role_map):
    guild = ctx.guild
    for role_name in role_map.values():
        existing_role = discord.utils.get(guild.roles, name=role_name)
        if not existing_role:
            await guild.create_role(name=role_name)
            await ctx.send(f"Created role: {role_name}")
        else:
            await ctx.send(f"Role {role_name} already exists.")

# Command: Start role setup
@bot.command()
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def start(ctx, channel: discord.TextChannel = None, timezone_name: str = None):
    timezone_name = timezone_name or os.getenv("REMINDER_TIMEZONE", "UTC")
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        await ctx.send("Unknown timezone. Use an IANA name such as America/New_York or UTC.")
        return
    if channel is not None and channel.guild.id != ctx.guild.id:
        await ctx.send("Choose a channel in this server.")
        return
    if not channel:
        channel = ctx.channel

    await ctx.send("Would you like to name the roles yourself? (yes/no)")
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ['yes', 'no']

    try:
        msg = await bot.wait_for('message', check=check, timeout=30.0)
    except asyncio.TimeoutError:
        await ctx.send('No response. Using default role names.')
        role_map = DEFAULT_ROLE_MAP.copy()
    else:
        if msg.content.lower() == 'yes':
            role_map = {}
            for emoji in DEFAULT_ROLE_MAP.keys():
                await ctx.send(f"Please enter the name for the role associated with {emoji}:")
                try:
                    role_name_msg = await bot.wait_for('message', check=lambda m: m.author == ctx.author and m.channel == ctx.channel, timeout=30.0)
                    role_map[emoji] = role_name_msg.content
                except asyncio.TimeoutError:
                    await ctx.send('No response. Using default role names for the remaining roles.')
                    role_map.update({k: v for k, v in DEFAULT_ROLE_MAP.items() if k not in role_map})
                    break
        else:
            role_map = DEFAULT_ROLE_MAP.copy()
    
    await create_roles(ctx, role_map)
    
    # Send the roles message to the specified channel
    message = await channel.send("React to this message to get roles:\n" + "\n".join([f"{emoji}: {role}" for emoji, role in role_map.items()]))
    for emoji in role_map.keys():
        await message.add_reaction(emoji)
    bot.settings.configure(ctx.guild.id, message.id, channel.id, role_map,
                           timezone_name, datetime.now(timezone.utc))
    await ctx.send(f"Setup saved. Saturday reminders use {timezone_name}.")


@bot.event
async def on_raw_reaction_add(payload):
    await handle_reaction(payload, add_role=True)


@bot.event
async def on_raw_reaction_remove(payload):
    await handle_reaction(payload, add_role=False)


async def handle_reaction(payload, add_role):
    if payload.guild_id is None:
        return
    settings = bot.settings.get(payload.guild_id)
    if settings is None or payload.message_id != settings["role_message_id"]:
        return
    role_name = settings["role_map"].get(str(payload.emoji))
    guild = bot.get_guild(payload.guild_id)
    if not role_name or guild is None:
        return
    try:
        member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
        if member.bot:
            return
        role = discord.utils.get(guild.roles, name=role_name)
        if role is None:
            logger.warning("Role %s missing in guild %s", role_name, guild.id)
            return
        if add_role:
            await member.add_roles(role)
        else:
            await member.remove_roles(role)
    except discord.HTTPException:
        logger.exception("Could not update reaction role in guild %s", guild.id)
        return
    try:
        action = "given" if add_role else "removed from"
        await member.send(f"The {role.name} role has been {action} you.")
    except discord.HTTPException:
        logger.info("Could not DM member %s", member.id)


async def dispatch_due(kind, now=None):
    await bot.wait_until_ready()
    supplied_now = now
    now = now or datetime.now(timezone.utc)
    emoji, reminder_text, _ = REMINDERS[kind]
    for settings, due in bot.settings.due(kind, now):
        try:
            if await send_role_reminder(settings, emoji, reminder_text):
                bot.settings.mark_sent(settings, kind, due, datetime.now(timezone.utc) if supplied_now is None else now)
        except discord.HTTPException:
            # Leave the deadline overdue to retry; other guilds still get reminders.
            logger.exception("Reminder failed in guild %s", settings["guild_id"])


@tasks.loop(minutes=1)
async def update_hydrated_roles():
    await dispatch_due("hydrated")


@tasks.loop(minutes=1)
async def update_bottle_check_roles():
    await dispatch_due("bottle")


@tasks.loop(minutes=1)
async def update_clean_room_roles():
    await dispatch_due("clean")


async def send_role_reminder(settings, emoji, reminder_text):
    channel = bot.get_channel(settings["reminder_channel_id"])
    if channel is None:
        channel = await bot.fetch_channel(settings["reminder_channel_id"])
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != settings["guild_id"]:
        logger.warning("Reminder channel unavailable for guild %s", settings["guild_id"])
        return False
    role_name = settings["role_map"].get(emoji)
    role = discord.utils.get(channel.guild.roles, name=role_name)
    if role is None:
        logger.warning("Role %s missing in guild %s", role_name, settings["guild_id"])
        return False
    await channel.send(f"{role.mention}, don't forget to {reminder_text}")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bot.run(os.getenv("Discord_Token"))
