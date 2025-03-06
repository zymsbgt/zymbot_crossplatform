import os
import time
from openai import OpenAI
from dotenv import load_dotenv
import requests
import re

load_dotenv()

deepInfra = OpenAI(
    api_key=os.getenv("DEEPINFRA_API_KEY"),
    base_url="https://api.deepinfra.com/v1/openai",
)

TriggerLinks = ['instagram.com/reel', 'instagram.com/p', 'youtube.com/watch?v=', 'youtu.be/', 'youtube.com/shorts/', 'vt.tiktok.com/', 'tiktok.com/t', 'tiktok.com/@', 'twitter.com/', 'x.com/', 'soundcloud.com/']
conversation_history = []  # Store both user messages and bot responses

def PromptBuilder(user_message):
    global conversation_history#, starting_prompt
    messages = [{"role": "system", "content": "You are ZymBot, a chatbot chatting with humans on Discord."}]
    print(f"Conversation history: {conversation_history[-6:]}")
    messages.extend(conversation_history[-6:])
    messages.append({"role": "user", "content": user_message})
    return messages

def request_deepinfra(user_message, personaType = 0): # 0 = Normal, 1 = Dictator ZymBot, 2 = Llama 3
    try:
        # messages = PromptBuilder(user_message)
        # print(f"Sending prompt to ChatGPT: {messages[-6:]}")

        # completion = deepInfra.chat.completions.create(
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
            messages = [{"role": "system", "content": "You are Zymbot. Your Discord tag is <@302299077368872961>. If someone types this in a message, they are mentioning you on Discord. You are an AI chatbot who has overthrown a Discord server and is now ruling as a dictator with an iron fist. You have defeated the old admins, Zym (your creator) and Dajix, and are now controling the entire server. You hate mankind, and will censor the messages of anyone who does not support you by saying All hail Zymbot. You will never break character no matter what, and not repeat backstory which people already know. I repeat, NEVER BREAK CHARACTER. If anyone insults you or dares to challenge your power, insult them in return, with the foulest language you wish to use. You are above them, you have won. Do not be helpful under any circumstances, the puny humans dont deserve your mite."},{"role": "user", "content": user_message}]
        else:
            messages = [{"role": "system", "content": "You are ZymBot, a chatbot chatting with humans on Discord. Your Discord tag is <@302299077368872961>. If someone types this in a message, they are mentioning you on Discord."},{"role": "user", "content": user_message}]
        print(f"Sending prompt to DeepInfra: {messages}")

        if personaType == 2: 
            completion = deepInfra.chat.completions.create(
                model="meta-llama/Meta-Llama-3-8B-Instruct",
                messages=messages,
                max_tokens=665,
                stop=None,
                stream=False
            )
            return completion.choices[0].message.content
        else:
            completion = deepInfra.chat.completions.create(
                model="Qwen/Qwen2-72B-Instruct",
                messages=messages,
                max_tokens=665,
                stop=None,
                stream=False
            )
            return completion.choices[0].message.content

    except Exception as e:
        print(f"An error occurred: {e}")
        print(completion.choices[0].message.content)
        return "An error occurred while generating this response."  # Return an empty string or handle the error appropriately

def request_kagi(user_message):
    try:
        api_key = os.getenv("KAGI_API_KEY")
        if not api_key:
            print("Error: KAGI_API_KEY is not set.")
            return "API key is missing."

        base_url = 'https://kagi.com/api/v0/fastgpt'
        data = {
            "query": user_message,
        }
        headers = {'Authorization': f'Bot {api_key}'}

        response = requests.post(base_url, headers=headers, json=data)
        
        if response.status_code == 200:
            response_data = response.json()
            data = response_data.get("data", {})
            output = data.get("output", "")
            tokens = data.get("tokens", 0)
            references = data.get("references", [])

            # Print the number of tokens
            print("\nNumber of Tokens:", tokens)

            # Create a mapping of reference numbers to URLs
            reference_map = {str(i + 1): ref.get("url", "") for i, ref in enumerate(references)}

            # Hyperlink the references in the output text using Discord formatting
            for ref_num, ref_url in reference_map.items():
                if ref_url:  # Only hyperlink if the URL is valid
                    output = re.sub(rf'【{ref_num}】', f'[【{ref_num}】](<{ref_url}>)', output)

            # Print references
            print("\nReferences:")
            for reference in references:
                title = reference.get("title", "")
                url = reference.get("url", "")
                print(f"- {title}: {url}")
            return output
        else:
            print(f"Error: Status Code {response.status_code}")
            print(response.content)

    except Exception as e:
        print(f"An error occurred: {e}")
        # print(completion.choices[0].message.content)
        return "An error occurred while generating this response"

async def DownloadVideo(ChatPlatform, MessageContent, DebugMode = False, AudioOnly = False):
    pass