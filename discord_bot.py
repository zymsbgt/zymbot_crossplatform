from common_utils import request_deepinfra, request_kagi, TriggerLinks, DownloadVideo
import discord
from discord.ext import commands
import asyncio

class DiscordBot:
    # Setup bot global variables here, if any

    def __init__(self, token):
        self.token = token
        intents = discord.Intents.default()
        intents.message_content = True
        self.DiscordBotClient = discord.Client(intents = intents)

    # ../bot.py will call this function upon startup
    def start(self):
        def CheckDebugMode(GuildId):
            if GuildId == 443253214859755522:
                return True
            return False

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
                
                # Create a downloader algorithm for Twitter

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
                if message.channel.id != 1220894297734512640 and message.channel.id != 1227499494388793345:
                    try:
                        async with message.channel.typing():
                            # Send prompt to ChatGPT
                            if message.guild is not None and message.guild.id == 443253214859755522 and message.channel.id == 1251486676736540772:
                                response = request_deepinfra(message.content, 1)
                            elif "flashteens" in message.content.lower() or "web search" in message.content.lower() or "roft" in message.content.lower():
                                if message.guild is None:
                                    response = "**Error:** Your message has triggered ZymBot to search the internet for answers. To prevent abuse, ZymBot does not access to a search engine for prompts made in Direct Messages. Please send your message in a public chat."
                                else:
                                    response = request_kagi(message.content)
                            elif message.guild is not None and message.guild.id == 612289903769944064:
                                print("Message sent in RoFT, using Llama 3")
                                response = request_deepinfra(message.content, 2)
                            else:
                                response = request_deepinfra(message.content, 0)

                            # TODO: If the Discord server ID is '612289903769944064', replace every Discord ping with the name of the user
                            response = response.replace("<@343451476137607179>", "FlashTeens")
                            response = response.replace("<@559210445991444480>", "OTS")
                            response = response.replace("<@1017991668194099200>", "FT Anti-Ping Bot")
                            await message.channel.send(response)
                    except Exception as e:
                        await message.channel.send(f"Error sending message: {e}")
                        print(response)

        self.DiscordBotClient.run(self.token)