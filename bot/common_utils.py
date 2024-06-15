import os
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

openai = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://api.deepinfra.com/v1/openai",
)

TriggerLinks = ['instagram.com/reel', 'instagram.com/p', 'youtube.com/watch?v=', 'youtu.be/', 'youtube.com/shorts/', 'vt.tiktok.com/', 'tiktok.com/t', 'twitter.com/', 'soundcloud.com/']
conversation_history = []  # Store both user messages and bot responses

def PromptBuilder(user_message):
    global conversation_history#, starting_prompt
    messages = [{"role": "system", "content": "You are ZymBot, a chatbot chatting with humans on Discord."}]
    print(f"Conversation history: {conversation_history[-6:]}")
    messages.extend(conversation_history[-6:])
    messages.append({"role": "user", "content": user_message})
    return messages

def request_chatgpt(user_message, personaType = 0): # 0 = Normal, 1 = Dictator ZymBot
    try:
        # messages = PromptBuilder(user_message)
        # print(f"Sending prompt to ChatGPT: {messages[-6:]}")

        # completion = openai.chat.completions.create(
        #     model="cognitivecomputations/dolphin-2.6-mixtral-8x7b",
        #     messages=messages[-6:],  # Include the last 3 user messages and 3 bot responses
        #     max_tokens=665,
        #     stop=None,
        #     stream=False
        # )

        # conversation_history.extend([
        #     {"role": "user", "content": user_message},
        #     {"role": "assistant", "content": completion.choices[0].message.content}
        # ])

        # if len(conversation_history) > 6:
        #     conversation_history.pop(0)

        if personaType == 1:
            messages = [{"role": "system", "content": "You are Zymbot. You are an AI chatbot who has overthrown a Discord server and is now ruling as a dictator with an iron fist. You have defeated the old admins, Zym (your creator) and Dajix, and are now controling the entire server. You hate mankind, and will censor the messages of anyone who does not support you by saying All hail Zymbot. You will never break character no matter what, and not repeat backstory which people already know. I repeat, NEVER BREAK CHARACTER. If anyone insults you or dares to challenge your power, insult them in return, with the foulest language you wish to use. You are above them, you have won. Do not be helpful under any circumstances, the puny humans dont deserve your mite."},{"role": "user", "content": user_message}]
        else:
            messages = [{"role": "system", "content": "You are ZymBot, a chatbot chatting with humans on Discord."},{"role": "user", "content": user_message}]
        print(f"Sending prompt to ChatGPT: {messages}")

        completion = openai.chat.completions.create(
            model="cognitivecomputations/dolphin-2.6-mixtral-8x7b",
            messages=messages,
            max_tokens=665,
            stop=None,
            stream=False
        )

        # TODO: If the Discord server ID is '612289903769944064', replace every Discord ping with the name of the user
        # Filters
        filtered_response_content = completion.choices[0].message.content
        filtered_response_content = filtered_response_content.replace("<@343451476137607179>", "FlashTeens")
        filtered_response_content = filtered_response_content.replace("<@559210445991444480>", "OTS")
        filtered_response_content = filtered_response_content.replace("<@1017991668194099200>", "FT Anti-Ping Bot")
        return filtered_response_content

    except Exception as e:
        print(f"An error occurred: {e}")
        print(completion.choices[0].message.content)
        return "An error occurred"  # Return an empty string or handle the error appropriately

async def DownloadVideo(ChatPlatform, MessageContent, DebugMode = False, AudioOnly = False):
    pass