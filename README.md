AquaTidyBot
AquaTidyBot is a Discord bot that helps users stay hydrated, check their bottles, and clean their rooms with periodic reminders and role management.

Features
Users can react to a message to get assigned specific roles.
Periodic reminders are sent to remind users to hydrate, check their bottles, and clean their rooms.
Customizable role names.
Automatic role creation and management.
Prerequisites
Python 3.8 or higher
Discord bot token

Usage
Commands
!start [channel]: Initializes the bot and sends a message to the specified channel (or current channel if not specified). Users can react to this message to get assigned roles.
Role Management
When the bot is initialized with the !start command, it will ask if you want to customize the role names. You can then provide names for the roles associated with each emoji:

🥤: Bottle Check
💧: Hydrated
🧹: Clean Room
Periodic Reminders
The bot sends periodic reminders to the channel it was initialized in:

update_hydrated_roles: Runs every 2 hours.
update_bottle_check_roles: Runs every 3 hours.
update_clean_room_roles: Runs every Saturday and then every 4 hours on that day.
Example
!start #bot-channel
This command will initialize the bot in the #bot-channel and send a message that users can react to for role assignment.

Contributing
Fork the repository.
Create a new branch: git checkout -b my-feature-branch.
Make your changes and commit them: git commit -m 'Add some feature'.
Push to the branch: git push origin my-feature-branch.
Submit a pull request.
License
This project is licensed under the MIT License. See the LICENSE file for details.

Acknowledgements
discord.py for providing the library to interact with the Discord API.
