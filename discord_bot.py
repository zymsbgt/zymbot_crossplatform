from common_utils import request_deepinfra, request_kagi, split_message, TriggerLinks, DownloadVideo
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import time

class DiscordBot:
    # Setup bot global variables here, if any
    NoReplyChannels = {1220894297734512640, 1227499494388793345} # ZymBot doesn't chat in these

    def __init__(self, token):
        self.token = token
        intents = discord.Intents.default()
        intents.message_content = True
        self.DiscordBotClient = discord.Client(intents = intents)
        # A plain Client has no slash commands of its own, so they hang off this tree
        self.CommandTree = app_commands.CommandTree(self.DiscordBotClient)

    # ../bot.py will call this function upon startup
    def start(self):
        def CheckDebugMode(GuildId):
            if GuildId == 443253214859755522:
                return True
            return False

        async def setup_hook():
            # Runs once before connecting. A global sync can take up to an hour to show a new command in Discord
            try:
                await self.CommandTree.sync()
            except discord.HTTPException as e:
                print(f"Could not sync slash commands: {e}")

        # Assigned rather than decorated with @event, because setup_hook is a Client method and not an event
        self.DiscordBotClient.setup_hook = setup_hook

        @self.CommandTree.command(name="web_search", description="Ask a question and get an answer from Kagi web search")
        @app_commands.describe(query="What you want to know")
        @app_commands.guild_only() # Same rule as the keyword trigger: no web search from Direct Messages
        @app_commands.checks.cooldown(1, 20.0) # Per user, since every search is a paid Kagi request
        async def search(interaction: discord.Interaction, query: app_commands.Range[str, 1, 500]):
            if interaction.channel_id in self.NoReplyChannels:
                await interaction.response.send_message("ZymBot doesn't reply in this channel.", ephemeral=True)
                return

            print(f'{interaction.user} used /web_search in "{interaction.guild.name}": {query}')

            # Kagi can take several seconds and Discord wants a reply within 3, so acknowledge first
            await interaction.response.defer(thinking=True)

            # request_kagi uses requests, which blocks. Off the event loop, the bot stays connected while it waits
            response = await asyncio.to_thread(request_kagi, query)
            if not response:
                response = "Kagi didn't return an answer. Please try again in a moment."

            for part in split_message(response):
                await interaction.followup.send(part, allowed_mentions=discord.AllowedMentions.none())

        @search.error
        async def search_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            if isinstance(error, app_commands.CommandOnCooldown):
                message = f"You're searching too fast - try again in {int(error.retry_after) + 1}s."
            else:
                print(f"/web_search error: {error}")
                message = "Something went wrong running that search."

            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)

        @self.DiscordBotClient.event
        async def on_ready():
            servers = self.DiscordBotClient.guilds
            print("Servers I'm currently in:")
            for server in servers:
                print(server.name)
            print('server successfully started as {0.user}'.format(self.DiscordBotClient))
            activity = discord.Activity(type=discord.ActivityType.listening, name="people I'm chatting with (ping me!)")
            await self.DiscordBotClient.change_presence(activity=activity)

        @self.DiscordBotClient.event
        async def on_message(message):
            isPinged = False

            if message.author == self.DiscordBotClient.user:
                return
            
            if self.DiscordBotClient.user.mentioned_in(message):
                if "@everyone" in message.content or "@here" in message.content:
                    return
                isPinged = True

            global TriggerLinks
            if any(keyword in message.content for keyword in TriggerLinks):
                if isPinged == False:
                    if message.guild is not None and message.guild.id == 612289903769944064: # RoFT Fan Chat
                        return
                    # await message.add_reaction("🎬")
                    # await message.add_reaction("🎵")
                else:
                    await DownloadVideo("discord", message.content, CheckDebugMode(message.guild.id))
                
                # TODO: Create a downloader algorithm for Twitter

            username = str(message.author).split('#')[0]

            if self.DiscordBotClient.user.mentioned_in(message):
                if message.guild is None:
                    print(f'{username} in Direct Message: {message.content}')
                else:
                    print(f'{username} on #{message.channel.name} in "{message.guild.name}": {message.content}')

                if any(links in message.content for links in TriggerLinks):
                    print("Download module activated, not replying with chatbot")
                    await DownloadVideo("discord", message.content, CheckDebugMode(message.guild.id))
                    return
                
                await asyncio.sleep(4)
                if message.channel.id not in self.NoReplyChannels:
                    try:
                        async with message.channel.typing():
                            # Send prompt to ChatGPT
                            if message.guild is not None and message.guild.id == 443253214859755522 and message.channel.id == 1251486676736540772: # Dictator ZymBot jail
                                response = request_deepinfra(message.content, 1)
                            elif "seahorse" in message.content.lower() and "emo" in message.content.lower():
                                time.sleep(4)
                                response = "There is no seahorse emoji in Ba Sing Se."
                            elif "flashteens" in message.content.lower() or "web search" in message.content.lower() or "roft" in message.content.lower():
                                if message.guild is None:
                                    response = "**Error:** Your message has triggered ZymBot to search the internet for answers. To prevent abuse, ZymBot does not have access to a search engine for prompts made in Direct Messages. Please send your message in a public chat."
                                else:
                                    response = request_kagi(message.content)
                            else:
                                response = request_deepinfra(message.content, 0)

                            #TODO: The response from the functions could either be a string or an array of strings. I need to modify this code to accomodate both string and array strings before sending
                            if isinstance(response, list):
                                for part in response:
                                    part = part.replace("<@343451476137607179>", "FlashTeens")
                                    part = part.replace("<@559210445991444480>", "OTS")
                                    part = part.replace("<@1017991668194099200>", "FT Anti-Ping Bot")
                                    await message.channel.send(part)
                            else:
                                response = response.replace("<@343451476137607179>", "FlashTeens")
                                response = response.replace("<@559210445991444480>", "OTS")
                                response = response.replace("<@1017991668194099200>", "FT Anti-Ping Bot")
                                await message.channel.send(response)
                    except Exception as e:
                        await message.channel.send(f"Error sending message: {e}")
                        print(response)

        self.DiscordBotClient.run(self.token)