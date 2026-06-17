import openai
import json
import asyncio

async def test_direct():
    client = openai.AsyncOpenAI(api_key="local-key", base_url="http://127.0.0.1:12345/v1")
    
    # Simple message history matching Turn 2
    messages = [
        {"role": "user", "content": "Open Notepad"},
        {"role": "assistant", "content": "[Action: Call bash with command notepad.exe]"},
        {"role": "user", "content": "[Tool Response for bash]: [Active Window]: \"Notepad\" (Class: Notepad, State: Normal)"}
    ]
    
    system_prompt = (
        "You are an expert desktop automation AI assistant.\n"
        "You MUST use tool calling to perform this task. Below are the available tools:\n"
        "[\n"
        "  {\n"
        "    \"type\": \"function\",\n"
        "    \"function\": {\n"
        "      \"name\": \"computer\",\n"
        "      \"description\": \"Control mouse and keyboard\",\n"
        "      \"parameters\": {\n"
        "        \"type\": \"object\",\n"
        "        \"properties\": {\n"
        "          \"action\": {\"type\": \"string\"},\n"
        "          \"text\": {\"type\": \"string\"}\n"
        "        }\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "]\n\n"
        "To call a tool, respond with a JSON markdown block of this exact format:\n"
        "```json\n"
        "{\n"
        "  \"thought\": \"your detailed thinking\",\n"
        "  \"tool_calls\": [\n"
        "    {\n"
        "      \"name\": \"tool_name\",\n"
        "      \"arguments\": {\"param\": \"value\"}\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "```"
    )
    
    formatted_messages = [{"role": "system", "content": system_prompt}] + messages
    
    print("Sending request to local VLM...")
    try:
        response = await client.chat.completions.create(
            model="google/gemma-4-12b-qat",
            messages=formatted_messages,
            temperature=0.0,
            max_tokens=2048
        )
        print("\n=== RAW RESPONSE ===")
        print(response.choices[0].message.content)
        print("====================")
        print(f"Finish reason: {response.choices[0].finish_reason}")
    except Exception as e:
        print(f"Error calling model: {e}")

asyncio.run(test_direct())
