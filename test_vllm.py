import urllib.request
import json
url = 'http://127.0.0.1:8095/v1/audio/speech'
body = json.dumps({'model': 'bosonai/higgs-audio-v3-tts-4b', 'input': 'Hi.', 'response_format': 'wav', 'voice': 'Ava_Sinclair'}).encode('utf-8')
req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as response:
        data = response.read()
        print('Response length:', len(data))
        print('First 50 bytes:', data[:50])
except Exception as e:
    print('Error:', e)
