# Computer Use Fine-Tuning Suite 🖥️🧠

This repository contains the ultimate toolset for generating synthetic training data to fine-tune Large Language Models (LLMs) and Vision-Language Models (VLMs) for native computer control.

By training on this data, you can teach models like **Qwen3.5-35B-A3B** natively understand Open Interpreter / MCP-style JSON action schemas without needing complex external prompting frameworks.

---

## 📂 File Overview

You now have a perfectly clean, two-script setup:

### `dataset_manager.py`
The unified CLI tool used to generate, merge, and output high-quality multi-turn jsonl training data.
- Stores 70 hand-crafted "Gold Standard" seeds natively internally.
- Calls an LLM API (Gemini/Local) to rapidly synthesize highly-reasoned logical bounds (using the seeds).
- Generates native OpenAI-formatted **Multimodal JSON Object (VLM)** arrays containing base64 images for Vision models.

### `train_qwen_tool_use.py`
The PyTorch/Transformers training loop designed explicitly to fine-tune models like Qwen3.5 using **Unsloth's `FastLanguageModel`**.
- Utilizes **bfloat16** native loading and Triton kernels to unlock 12x faster MoE training, explicitly skipping 4-bit as per Unsloth's latest MoE docs.
- Outputs an instantly plug-and-play **LoRA adapter** rather than overwriting full model weights.
- Implements strict `DataCollatorForCompletionOnlyLM` to ensure the model *only* calculates its loss on the `assistant` JSON outputs (it safely ignores the `user` and `tool` contexts so it doesn't try to memorize them).

---

## 🛠️ Generating Datasets

Use the `dataset_manager.py` file to output the training data format you need.

### 1. The Gold Standard Seeds
Extract the 70 perfectly hand-crafted multi-turn scenarios directly from the python code into a clean JSONL.
```bash
python dataset_manager.py seeds --out manual_seeds.jsonl
```

### 2. API Reasoning Synthesis (Gemini & Local LLMs)
Send the manual seeds into an LLM API using few-shot prompting to perfectly generate extremely high-reasoning, complex permutations.

**For Gemini (API Key Required):**
```bash
python dataset_manager.py api --count 5000 --api-key YOUR_GEMINI_KEY --out synthetic_api.jsonl
```

**For Local LLMs (Ollama, LM Studio, vLLM):**
```bash
python dataset_manager.py api --count 5000 --api-base http://localhost:11434/v1 --model qwen2.5 --out synthetic_local.jsonl
```

### 3. Vision Language Model (VLM) Native Generation
If fine-tuning **Qwen3.5-VL** (multimodal vision model), you must train it using base64 image strings interleaved in the user and tool result message arrays.
```bash
python dataset_manager.py vlm --count 1500 --out vision_training.jsonl
```

---

## 🚀 Training the Model

Once your `.jsonl` dataset is ready, pass it to the LoRA training script.

```bash
python train_qwen_tool_use.py --dataset manual_seeds.jsonl
```
*(Ensure you modify the script `MODEL_NAME` to point to your local Qwen3.5-35B-A3B or Qwen-VL weights if using a custom local directory instead of HuggingFace.)*

---

## 💡 The "Thin Client" Native Execution Strategy

Unlike traditional MCP approaches where an external bridging server prompts the generic LLM, the output of **this fine-tuned model** will be native perfection. 

To execute it directly on your OS, you no longer require large MCP modules! 
You can write a simple python script leveraging lightweight tools like `pyautogui` and native python `subprocess`:
```python
# The Thin Client loop:
model_output = local_llm.generate("Open the terminal.")
tool_call = json.loads(model_output)["function"]
tool_name = tool_call["name"]
args = json.loads(tool_call["arguments"])

if tool_name == "computer" and args["action"] == "left_click":
    pyautogui.click(*args["coordinate"])
elif tool_name == "bash":
    subprocess.run(args["command"], shell=True)
```
Enjoy complete native, private, instant agentic OS control with the standard Anthropic MCP Schema!
