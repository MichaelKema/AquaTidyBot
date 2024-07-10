import discord
import asyncio
from dotenv import load_dotenv
from discord.ext import tasks, commands
import os
from datetime import datetime, timedelta

# Set up intents
intents = discord.Intents.default()
intents.message_content = True  # Enables access to message content
intents.members = True  # Enables access to member details

# Create bot instance with intents
bot = commands.Bot(command_prefix="!", intents=intents)

# Default role map
DEFAULT_ROLE_MAP = {
    "🥤": "Bottle Check",
    "💧": "Hydrated",
    "🧹": "Clean Room"
}

# Initialize role message ID and role map
bot.role_message_id = None
bot.role_map = DEFAULT_ROLE_MAP.copy()
bot.reminder_channel_id = None  # Initialize reminder channel ID

# Load environment variables
load_dotenv()
TOKEN = os.getenv('Discord_Token')

# Event: Bot ready
@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    update_hydrated_roles.start()  # Start the hydrated reminder loop
    update_bottle_check_roles.start()  # Start the bottle check reminder loop
    update_clean_room_roles.start()  # Start the clean room reminder loop

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
@commands.has_permissions(administrator=True)
async def start(ctx, channel: discord.TextChannel = None):
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
    
    bot.role_map = role_map  # Update bot's role map
    await create_roles(ctx, role_map)
    
    # Send the roles message to the specified channel
    message = await channel.send("React to this message to get roles:\n" + "\n".join([f"{emoji}: {role}" for emoji, role in role_map.items()]))
    for emoji in role_map.keys():
        await message.add_reaction(emoji)
    bot.role_message_id = message.id

    # Store the reminder channel ID
    bot.reminder_channel_id = channel.id

# Event: Reaction added
@bot.event
async def on_reaction_add(reaction, user):
    if reaction.message.id == bot.role_message_id and not user.bot:
        await handle_reaction(reaction, user, add_role=True)

# Event: Reaction removed
@bot.event
async def on_reaction_remove(reaction, user):
    if reaction.message.id == bot.role_message_id and not user.bot:
        await handle_reaction(reaction, user, add_role=False)

# Function to handle role addition/removal based on reaction
async def handle_reaction(reaction, user, add_role):
    guild = reaction.message.guild
    emoji = str(reaction.emoji)
    
    role_name = bot.role_map.get(emoji)  # Use bot's role map
    if role_name:
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            if add_role:
                await user.add_roles(role)
                await user.send(f"You have been given the {role.name} role.")
            else:
                await user.remove_roles(role)
                await user.send(f"The {role.name} role has been removed from you.")
        else:
            await reaction.message.channel.send(f"Role for {emoji} not found. It may have been renamed or deleted.")

# Task: Update Hydrated Roles (Every 2 Hours)
@tasks.loop(hours=2)
async def update_hydrated_roles():
    await send_role_reminder("💧", "stay hydrated!")

# Task: Update Bottle Check Roles (Every 3 Hours)
@tasks.loop(hours=3)
async def update_bottle_check_roles():
    await send_role_reminder("🥤", "check your bottles!")

# Task: Update Clean Room Roles (Every Saturday and then every 4 hours)
@tasks.loop(minutes=1)  # Loop every minute to check if it's Saturday
async def update_clean_room_roles():
    now = datetime.now()
    if now.weekday() == 5:  # Check if today is Saturday (weekday() returns 5 for Saturday)
        if now.hour % 4 == 0 and now.minute == 0:  # Every 4 hours on Saturday
            await send_role_reminder("🧹", "clean your room!")

# Function to send role reminder
async def send_role_reminder(emoji, reminder_text):
    if bot.reminder_channel_id:
        channel = bot.get_channel(bot.reminder_channel_id)
        if channel:
            role_name = bot.role_map.get(emoji)
            if role_name:
                role = discord.utils.get(channel.guild.roles, name=role_name)
                if role:
                    await channel.send(f"{role.mention}, don't forget to {reminder_text}")
                else:
                    print(f"Role '{role_name}' not found in the guild.")
            else:
                print(f"No role name mapped for emoji '{emoji}'.")
        else:
            print(f"Channel with ID {bot.reminder_channel_id} not found.")

# Run the bot
bot.run(TOKEN)
