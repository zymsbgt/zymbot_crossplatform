from bot.common_utils import request_chatgpt, TriggerLinks, DownloadVideo
import discord
import asyncio

class DiscordBot:
    # Setup bot global variables here

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
            print('Server successfully started as {0.user}'.format(self.DiscordBotClient))
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
                    if message.guild is not None:
                        if message.guild.id == 612289903769944064: # RoFT Fan Chat
                            return
                    await message.add_reaction("🎬")
                    await message.add_reaction("🎵")
                else:
                    await DownloadVideo("discord", message.content, CheckDebugMode(message.guild.id))
                
                # Create a downloader algorithm for Twitter

            username = str(message.author).split('#')[0]
            user_message = str(message.content)
            channel = str(message.channel.name)
            guild = str(message.guild.name)

            if self.DiscordBotClient.user.mentioned_in(message):
                print(f'{username} on #{channel} in "{guild}": {user_message}')

                if any(links in message.content for links in TriggerLinks):
                    print("Download module activated, not replying with chatbot")
                    await DownloadVideo("discord", message.content, CheckDebugMode(message.guild.id))
                    return
                
                await asyncio.sleep(4)
                if message.channel.id != 1220894297734512640 or 1227499494388793345:
                    try:
                        async with message.channel.typing():
                            # Send prompt to ChatGPT
                            if message.guild is not None:
                                if message.guild.id == 443253214859755522:
                                    if response = request_chatgpt(user_message, 1)
                            else:
                                response = request_chatgpt(user_message)
                            await message.channel.send(response)
                    except Exception as e:
                        await message.channel.send(f"Error sending message: {e}")
                        print(response)

        self.DiscordBotClient.run(self.token)

    # Other Discord-specific methods
