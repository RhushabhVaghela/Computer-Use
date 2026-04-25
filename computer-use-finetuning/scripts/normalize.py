import json
import os
from copy import deepcopy

# -------- paths --------
# Input: the current (possibly concatenated, partially-clean) file
input_file  = r"D:\Agents-and-other-repos\oi-computer-use-mcp\computer-use-finetuning\datasets\synthetic_dataset.jsonl"
# Output: final, clean JSONL
output_file = r"D:\Agents-and-other-repos\oi-computer-use-mcp\computer-use-finetuning\datasets\synthetic_dataset_final.jsonl"

# Ensure the output directory exists
os.makedirs(os.path.dirname(output_file), exist_ok=True)

fixed_messages = 0
fixed_tool_calls_format = 0
fixed_tool_call_args = 0
dropped_lines = 0

with open(input_file, 'r', encoding='utf-8') as infile, \
     open(output_file, 'w', encoding='utf-8') as outfile:
    
    for i, line in enumerate(infile):
        line = line.strip()
        if not line:
            continue
            
        try:
            data = json.loads(line)
            
            if "messages" in data:
                clean_messages = []
                for msg in data["messages"]:
                    
                    # Fix 1: Handle malformed array structures (e.g., ["user", "hello"])
                    if isinstance(msg, list) and len(msg) >= 2:
                        msg = {
                            "role": str(msg[0]),
                            "content": str(msg[1])
                        }
                        fixed_messages += 1
                        
                    # Proceed only if the message is a valid dictionary
                    if isinstance(msg, dict):
                        
                        if "tool_calls" in msg:
                            # Fix 3 (NEW): Wrap single tool_call objects into a list
                            if isinstance(msg["tool_calls"], dict):
                                msg["tool_calls"] = [msg["tool_calls"]]
                                fixed_tool_calls_format += 1
                                
                            # Fix 2: Handle malformed tool_call arguments (object to string)
                            if isinstance(msg["tool_calls"], list):
                                for tool_call in msg["tool_calls"]:
                                    if isinstance(tool_call, dict) and "function" in tool_call and isinstance(tool_call["function"], dict):
                                        if "arguments" in tool_call["function"]:
                                            args = tool_call["function"]["arguments"]
                                            if isinstance(args, dict):
                                                tool_call["function"]["arguments"] = json.dumps(args)
                                                fixed_tool_call_args += 1
                        
                        # Only keep messages that have at least a role
                        if "role" in msg:
                            clean_messages.append(msg)
                            
                data["messages"] = clean_messages
                
            outfile.write(json.dumps(data) + "\n")
            
        except json.JSONDecodeError:
            print(f"Skipping line {i+1}: Invalid JSON structure.")
            dropped_lines += 1

print(f"Normalization complete!")
print(f"Fixed {fixed_messages} malformed array messages.")
print(f"Fixed {fixed_tool_calls_format} malformed tool_calls (object to array).")
print(f"Fixed {fixed_tool_call_args} malformed tool call arguments (object to string).")
if dropped_lines > 0:
    print(f"Dropped {dropped_lines} completely unreadable lines.")
print(f"Saved strictly-typed dataset to: {output_file}")