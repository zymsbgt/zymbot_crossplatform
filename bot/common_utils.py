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

        

        messages = [{"role": "system", "content": "You are ZymBot, a chatbot chatting with humans on Discord."},{"role": "user", "content": user_message}]
        print(f"Sending prompt to ChatGPT: {messages}")

        completion = openai.chat.completions.create(
            model="cognitivecomputations/dolphin-2.6-mixtral-8x7b",
            messages=messages,
            max_tokens=665,
            stop=None,
            stream=False
        )

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