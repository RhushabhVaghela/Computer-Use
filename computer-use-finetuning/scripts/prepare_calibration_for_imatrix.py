import json
import argparse
import os

def main():
    parser = argparse.ArgumentParser(description="Convert JSONL training data to raw text for imatrix calibration.")
    parser.add_argument("--input", required=True, help="Path to the synthetic_dataset.jsonl file")
    parser.add_argument("--output", required=True, help="Path where calibration_data.txt will be saved")
    parser.add_argument("--max_examples", type=int, default=500, help="Number of examples to extract (default: 500)")

    args = parser.parse_args()

    # Convert paths to absolute to ensure WSL handles them correctly
    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)

    print(f"Reading dataset from {input_path}...")
    calibration_text = ""
    count = 0

    if not os.path.exists(input_path):
        print(f"❌ Error: Input file not found at {input_path}")
        return

    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            if count >= args.max_examples:
                break
            try:
                data = json.loads(line)
                # Build the conversation text manually to avoid tokenizer/template crashes
                for msg in data["messages"]:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    
                    # Ensure tool calls are captured as text to calibrate those specific weights
                    if "tool_calls" in msg and msg["tool_calls"]:
                        content += "\n" + json.dumps(msg["tool_calls"])
                    
                    if content:
                        calibration_text += f"<|im_start|>{role}\n{content}<|im_end|>\n"
                
                calibration_text += "\n\n"
                count += 1
            except Exception as e:
                continue # Skip malformed lines

    print(f"Writing {count} formatted examples to {output_path}...")
    with open(output_path, 'w', encoding='utf-8') as out_f:
        out_f.write(calibration_text)

    print("✅ Done! You can now use this .txt file for the --imatrix_data argument in the main pipeline.")

if __name__ == "__main__":
    main()