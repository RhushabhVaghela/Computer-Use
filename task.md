# Task Checklist: VLM Optimization & Voice/Screen Capture Architecture

- [/] Implement VLM Latency & Active Window Intelligence
  - [/] Add `prune_message_history` in [run_agent.py](file:///d:/Agents-and-other-repos/Computer-Use/src/run_agent.py) to prune screenshots and truncate older UI/DOM trees.
  - [ ] Integrate updated system prompts (focus/minimized window recovery instructions) in [run_agent.py](file:///d:/Agents-and-other-repos/Computer-Use/src/run_agent.py) and [stress_test_suite.py](file:///d:/Agents-and-other-repos/Computer-Use/tests/stress_test_suite.py).
  - [ ] Verify latency is < 2.0s and active window recovery succeeds by running Scenario 1 and Scenario 3.
- [ ] Build Capture & Voice Core Pipelines
  - [ ] Implement [capture_service.py](file:///d:/Agents-and-other-repos/Computer-Use/src/capture_service.py) supporting both native `mss`+`pyaudio` and local `screenpipe` connectors.
  - [ ] Implement [speech_processor.py](file:///d:/Agents-and-other-repos/Computer-Use/src/speech_processor.py) with Whisper `large-v3-turbo` GPU transcription and Kokoro/XTTS text-to-speech.
  - [ ] Implement [voice_server.py](file:///d:/Agents-and-other-repos/Computer-Use/src/voice_server.py) managing a WebSocket/WebRTC communication loop linking user audio and screen frames with the local VLM.
- [ ] Create Web Client UI (AI Studio Style)
  - [ ] Implement [voice_client.html](file:///d:/Agents-and-other-repos/Computer-Use/tests/voice_client.html) for visual screen/tab sharing, microphone streaming, and voice playback.
- [ ] Verify & Document
  - [ ] Run benchmark tests for the real-time loop.
  - [ ] Write a comparative analysis of Screenpipe vs Custom Daemon in [walkthrough.md](file:///C:/Users/Rhushabh/.gemini/antigravity-ide/brain/c3ba77f8-2040-4f8d-ab93-67d3da6f4e68/walkthrough.md).
