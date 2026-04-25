import os
import sys
import time
import logging
import argparse
import subprocess
import glob
from datetime import timedelta
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text

# Set this to the absolute path of your llama.cpp repository
ROOTPATH = "/mnt/d/Agents-and-other-repos/llama.cpp"

# Master list of supported llama.cpp quantizations
SUPPORTED_QUANTS = [
    "Q4_0", "Q4_1", "Q5_0", "Q5_1", "Q8_0",
    "Q2_K", "Q3_K_S", "Q3_K_M", "Q3_K_L",
    "Q4_K_S", "Q4_K_M", "Q5_K_S", "Q5_K_M", "Q6_K",
    "IQ2_XXS", "IQ2_XS", "IQ2_S",
    "IQ3_XXS", "IQ3_S", "IQ3_M",
    "IQ4_NL", "IQ4_XS",
    "F16", "F32", "BF16"
]

# --- Setup Logging ---
log_file = "quantization_pipeline.log"
logging.basicConfig(
    filename=log_file,
    filemode="w",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
console = Console()

def get_vram_gb():
    """Detect total VRAM using nvidia-smi."""
    try:
        res = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"])
        return int(res.decode().strip()) / 1024
    except:
        return 0

def windows_to_wsl(path: str) -> str:
    """Convert X:\\... Windows paths to /mnt/x/... WSL-style paths."""
    if not path:
        return path
    path = path.replace("\\", "/")
    if ":" in path:
        drive, rest = path.split(":", 1)
        if rest.startswith("/"):
            rest = rest[1:]
        return f"/mnt/{drive.lower()}/{rest}"
    return path

def run_command(command, task_name, progress, task_id):
    """Executes a shell command, logs output, and handles errors."""
    logging.info(f"--- STARTING: {task_name} ---")
    logging.info(f"Command: {' '.join(command)}")

    try:
        process = subprocess.Popen(
            command,
            cwd=ROOTPATH,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True,
        )

        for line in process.stdout:
            logging.debug(line.strip())

        process.wait()

        if process.returncode != 0:
            console.print(f"\n[bold red]❌ Error during {task_name}. Check {log_file} for details.[/bold red]")
            logging.error(f"Process exited with code {process.returncode}")
            sys.exit(1)

        progress.update(task_id, advance=1, description=f"[green]✔ {task_name} Complete!")
        logging.info(f"--- FINISHED: {task_name} ---")

    except Exception as e:
        console.print(f"\n[bold red]❌ Critical failure during {task_name}: {e}[/bold red]")
        logging.error(f"Exception: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Automated GGUF Merge & Quantization Pipeline")
    parser.add_argument("--base", required=False, help="Path to base model directory")
    parser.add_argument("--lora", required=False, help="Path to LoRA adapter directory")
    parser.add_argument("--merged_gguf", required=False, help="Path to an ALREADY MERGED f16 GGUF file")
    parser.add_argument("--output_dir", required=True, help="Directory to save final models")
    parser.add_argument("--quant", required=True, nargs='+', help="Quantization formats (e.g., IQ2_XS Q4_K_M)")
    parser.add_argument("--gguf", action="store_true", help="Skip HF->GGUF conversion (assume inputs are GGUF)")
    parser.add_argument("--imatrix", required=False, help="Path to an EXISTING imatrix.dat file")
    parser.add_argument("--imatrix_data", required=False, help="Path to a calibration .txt file to GENERATE imatrix.dat")
    # NECESSARY CHANGES FOR SPEED:
    parser.add_argument("--ngl", type=int, default=33, help="Number of GPU layers to offload (default: 33 for 16GB VRAM)")
    parser.add_argument("--ctx", type=int, default=1024, help="Context size for imatrix generation (default: 1024)")
    args = parser.parse_args()

    console.print(Panel.fit("[bold cyan]🤖 Llama.cpp Orchestrator: Multi-Quantization & Multimodal[/bold cyan]"))
    
    # 1. Path Resolution & Logic Check
    if args.merged_gguf:
        merged_gguf = os.path.abspath(windows_to_wsl(args.merged_gguf))
        base_name = os.path.splitext(os.path.basename(merged_gguf))[0].replace("-merged-f16", "")
    else:
        if not (args.base and args.lora):
            console.print("[bold red]❌ Error: You must provide either (--base AND --lora) OR --merged_gguf.[/bold red]")
            sys.exit(1)
        base_path = os.path.abspath(windows_to_wsl(args.base))
        lora_path = os.path.abspath(windows_to_wsl(args.lora))
        base_name = os.path.basename(base_path.rstrip("/\\"))

    output_dir_path = os.path.abspath(windows_to_wsl(args.output_dir))
    imatrix_path = os.path.abspath(windows_to_wsl(args.imatrix)) if args.imatrix else None
    imatrix_data_path = os.path.abspath(windows_to_wsl(args.imatrix_data)) if args.imatrix_data else None

    os.makedirs(output_dir_path, exist_ok=True)

    # 2. UI Validation & Supported Quantization Grid
    selected_quants = [q.upper() for q in args.quant]
    iq_requested = any(q.startswith("I") for q in selected_quants)
    
    console.print("[bold]Available Formats:[/bold]")
    grid_items = []
    for q in SUPPORTED_QUANTS:
        if q in selected_quants:
            grid_items.append(Text(q, style="bold green"))
        else:
            grid_items.append(Text(q, style="dim white"))
    console.print(Panel(Columns(grid_items, equal=True, expand=True)))

    # --- NECESSARY CHANGE: Smart Hardware Check ---
    vram = get_vram_gb()
    # Estimate F16 size (~54GB) if not yet existing
    model_size_gb = os.path.getsize(merged_gguf) / (1024**3) if os.path.exists(merged_gguf) else 54
    use_proxy = model_size_gb > vram and imatrix_data_path is not None
    
    if use_proxy:
        console.print(f"[bold yellow]⚠️  Model size ({model_size_gb:.1f}GB) > VRAM ({vram:.1f}GB).[/bold yellow]")
        console.print("[bold cyan]🚀 Smart Proxy enabled: Creating a temporary Q4 model for fast imatrix generation.[/bold cyan]")

    invalid_quants = [q for q in selected_quants if q not in SUPPORTED_QUANTS]
    if invalid_quants:
        console.print(f"[bold red]❌ Error: Unsupported formats requested: {', '.join(invalid_quants)}[/bold red]")
        sys.exit(1)

    if iq_requested and not (imatrix_path or imatrix_data_path):
        console.print("[bold red]❌ Error: 'I' series formats REQUIRE imatrix data.[/bold red]")
        sys.exit(1)

    # 3. Multimodal Component Detection
    is_vlm = False
    if not args.merged_gguf and os.path.exists(os.path.join(base_path, "preprocessor_config.json")):
        is_vlm = True
        console.print("[bold magenta]👁️  Vision-Language Model detected! mmproj will be extracted.[/bold magenta]")

    console.print(f"Logging all debug info to: [bold yellow]{log_file}[/bold yellow]\n")

    # 4. Define Command List
    start_time = time.time()
    commands = []

    if not args.merged_gguf:
        base_gguf = os.path.join(output_dir_path, f"{base_name}-base-f16.gguf")
        lora_gguf = os.path.join(output_dir_path, "adapter-f16.gguf")
        merged_gguf = os.path.join(output_dir_path, f"{base_name}-merged-f16.gguf")
        
        if not args.gguf:
            commands.append(("Converting Base Model to GGUF (f16)", ["python", "convert_hf_to_gguf.py", base_path, "--outfile", base_gguf]))
            commands.append(("Converting LoRA to GGUF", ["python", "convert_lora_to_gguf.py", lora_path, "--outfile", lora_gguf]))
            if is_vlm:
                commands.append(("Extracting Multimodal Projector (mmproj)", ["python", "examples/llava/convert_image_encoder_to_gguf.py", "-m", base_path, "--output-dir", output_dir_path]))
            bake_base, bake_lora = base_gguf, lora_gguf
        else:
            bake_base, bake_lora = base_path, lora_path

        commands.append(("Baking LoRA into Base Model", ["build/bin/llama-export-lora", "-m", bake_base, "--lora", bake_lora, "-o", merged_gguf]))

    # Step: Imatrix Generation (with Smart Proxy logic)
    if imatrix_data_path and not imatrix_path:
        target_imatrix_model = merged_gguf
        if use_proxy:
            proxy_path = os.path.join(output_dir_path, "temp_proxy_for_imatrix.gguf")
            # Step A: Create Proxy Q4
            commands.append(("Creating Proxy Q4 for imatrix", ["build/bin/llama-quantize", merged_gguf, proxy_path, "Q4_K_M"]))
            target_imatrix_model = proxy_path
        
        gen_imatrix_path = os.path.join(output_dir_path, f"{base_name}-imatrix.dat")
        # Step B: Run Imatrix on Proxy
        commands.append(("Generating Importance Matrix", [
            "build/bin/llama-imatrix", "-m", target_imatrix_model, "-f", imatrix_data_path, 
            "-o", gen_imatrix_path, "--ctx-size", str(args.ctx), "-ngl", "64" # Use full NGL for proxy speed
        ]))
        imatrix_path = gen_imatrix_path

    # Step: Quantization Loop
    for q in selected_quants:
        final_file = os.path.join(output_dir_path, f"{base_name}-{q}.gguf")
        q_cmd = ["build/bin/llama-quantize"]
        if imatrix_path and (q.startswith("I") or q == "Q2_K"):
            q_cmd.extend(["--imatrix", imatrix_path])
        q_cmd.extend([merged_gguf, final_file, q])
        commands.append((f"Quantizing to {q}", q_cmd))

    # 5. Execution Engine
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(), TimeRemainingColumn(), console=console, transient=False
    ) as progress:
        
        main_task = progress.add_task("[bold blue]Pipeline Progress...", total=len(commands))

        for step_name, cmd in commands:
            step_task = progress.add_task(f"[cyan]Running: {step_name}...", total=1)
            run_command(cmd, step_name, progress, step_task)
            progress.update(main_task, advance=1)

            # --- POST-STEP CLEANUP ---
            if step_name == "Extracting Multimodal Projector (mmproj)":
                for f in glob.glob(os.path.join(output_dir_path, "*mmproj*.gguf")):
                    if "BF16" not in f:
                        os.rename(f, os.path.join(output_dir_path, "mmproj-BF16.gguf"))

            if step_name == "Baking LoRA into Base Model" and not args.gguf:
                if os.path.exists(base_gguf): os.remove(base_gguf)
                if os.path.exists(lora_gguf): os.remove(lora_gguf)
            
            # Action: Delete proxy model once imatrix is done
            if step_name == "Generating Importance Matrix" and use_proxy:
                if os.path.exists(proxy_path): 
                    os.remove(proxy_path)
                    logging.info("Deleted temporary proxy GGUF.")

    # 6. Final Report
    elapsed = time.time() - start_time
    summary = (
        f"[bold green]🎉 All Quantizations Complete![/bold green]\n\n"
        f"[bold]Total Runtime:[/bold] {str(timedelta(seconds=int(elapsed)))}\n"
        f"[bold]Output Directory:[/bold] {output_dir_path}\n"
        f"[bold]Generated Files:[/bold] {len(selected_quants)} models"
    )
    console.print(Panel.fit(summary, border_style="green"))

if __name__ == "__main__":
    main()