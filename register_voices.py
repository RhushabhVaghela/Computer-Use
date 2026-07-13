import os
import sys
import glob
import requests

def register_voices():
    voices_dir = os.path.join(os.path.dirname(__file__), "reference-voices")
    vllm_voices_url = "http://127.0.0.1:8095/v1/audio/voices"
    
    print(f"Scanning for voices in {voices_dir}...")
    voice_files = glob.glob(os.path.join(voices_dir, "*.mp3")) + glob.glob(os.path.join(voices_dir, "*.wav"))
    
    if not voice_files:
        print("No .mp3 or .wav voices found in reference-voices.")
        return
        
    voice_types = {
        "Ava_Sinclair": "(Upbeat · Clear)",
        "Diane_Whitfield": "(Professional · Serious)",
        "Eleanor_Reed": "(Calm · Articulate)",
        "Ethan_Cole": "(Thoughtful · Warm)",
        "Greg_Mason": "(Calm · Instructive)",
        "Jake_Rivers": "(Energetic · Dramatic)",
        "Marcus_Webb": "(Enthusiastic · Confident)",
        "Mia_Sullivan": "(Conversational · Energetic)",
        "Nora_Vance": "(Calm · Narrative)",
        "Oliver_Grant": "(Articulate · Reflective)",
        "Vivian_Shaw": "(Confident · Steady)"
    }
        
    for filepath in voice_files:
        filename = os.path.basename(filepath)
        voice_name = os.path.splitext(filename)[0]
        v_type = voice_types.get(voice_name, "")
        
        print(f"Uploading voice '{voice_name}' {v_type}...")
        try:
            with open(filepath, 'rb') as f:
                files = {
                    'audio_sample': (filename, f, 'audio/mpeg' if filepath.endswith('.mp3') else 'audio/wav')
                }
                data = {
                    'name': voice_name,
                    'consent': 'true'
                }
                response = requests.post(vllm_voices_url, files=files, data=data)
                
            if response.status_code == 200:
                print(f"  [OK] Successfully registered '{voice_name}'")
            else:
                print(f"  [ERROR] Failed to register '{voice_name}': HTTP {response.status_code}")
                print(f"          {response.text}")
        except requests.exceptions.ConnectionError:
            print(f"  [ERROR] Could not connect to vLLM at {vllm_voices_url}. Is the server running on port 8095?")
            sys.exit(1)
        except Exception as e:
            print(f"  [ERROR] Exception uploading '{voice_name}': {e}")

if __name__ == "__main__":
    register_voices()
