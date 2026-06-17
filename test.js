
        const serverAddress = document.getElementById("server-address");
        const ttsVoice = document.getElementById("tts-voice");
        const connectBtn = document.getElementById("connect-btn");
        const screenBtn = document.getElementById("screen-btn");
        const previewVideo = document.getElementById("preview-video");
        const captureCanvas = document.getElementById("capture-canvas");
        const previewPlaceholder = document.getElementById("preview-placeholder");
        const logsFeed = document.getElementById("logs-feed");
        const textInput = document.getElementById("text-input");
        const sendBtn = document.getElementById("send-btn");
        const statusIndicator = document.getElementById("status-indicator");
        const statusText = document.getElementById("status-text");
        const visualizerRing = document.getElementById("visualizer-ring");

        let ws = null;
        let screenStream = null;
        let audioContext = null;
        let micStream = null;
        let micProcessor = null;
        let screenInterval = null;
        let audioQueue = [];
        let isPlayingAudio = false;
        let isProcessing = false;
        let echoTimeout = null;

        // --- Logger Helper ---
        function addLog(role, text) {
            const entry = document.createElement("div");
            entry.className = "log-entry";
            
            const roleSpan = document.createElement("span");
            roleSpan.className = `log-role ${role}`;
            roleSpan.textContent = role;
            
            const textSpan = document.createElement("span");
            textSpan.className = "log-text";
            textSpan.textContent = text;
            
            entry.appendChild(roleSpan);
            entry.appendChild(textSpan);
            logsFeed.appendChild(entry);
            logsFeed.scrollTop = logsFeed.scrollHeight;
        }

        // --- Server Connection ---
        connectBtn.addEventListener("click", () => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                closeConnection();
            } else {
                openConnection();
            }
        });

        function openConnection() {
            addLog("system", `Connecting to server at ${serverAddress.value}...`);
            statusIndicator.className = "status-dot processing";
            statusText.textContent = "Connecting";
            
            ws = new WebSocket(serverAddress.value);
            
            ws.onopen = () => {
                addLog("system", "Connected to Voice Server.");
                statusIndicator.className = "status-dot connected";
                statusText.textContent = "Connected";
                connectBtn.textContent = "Disconnect";
                screenBtn.disabled = false;
                textInput.disabled = false;
                sendBtn.disabled = false;
                
                // Initialize audio contexts
                initAudio();
                
                // Auto-start screen share
                if (!screenStream) {
                    startScreenSharing();
                }
            };
            
            ws.onclose = () => {
                addLog("system", "Disconnected from server.");
                closeConnection();
            };
            
            ws.onerror = (err) => {
                addLog("system", `WebSocket Error: Connection failed.`);
                statusIndicator.className = "status-dot error";
                statusText.textContent = "Error";
            };

            ws.onmessage = async (event) => {
                if (event.data instanceof Blob) {
                    // Speech audio response (WAV)
                    const arrayBuffer = await event.data.arrayBuffer();
                    playAudioBuffer(arrayBuffer);
                } else {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.type === "transcript") {
                            addLog("user", data.text);
                            visualizerRing.className = "pulse-ring listening";
                            isProcessing = true; // Wait for VLM
                        } else if (data.type === "thought") {
                            addLog("assistant", data.text);
                        } else if (data.type === "action") {
                            addLog("system", data.text);
                        } else if (data.type === "status") {
                            statusText.textContent = data.text;
                            if (data.text === "Thinking...") {
                                isProcessing = true;
                            } else if (data.text === "Connected") {
                                isProcessing = false;
                            }
                        }
                    } catch (e) {
                        logger.error(e);
                    }
                }
            };
        }

        function closeConnection() {
            if (ws) {
                ws.close();
                ws = null;
            }
            stopScreenSharing();
            stopAudioInput();
            statusIndicator.className = "status-dot";
            statusText.textContent = "Disconnected";
            connectBtn.textContent = "Connect Server";
            screenBtn.disabled = true;
            textInput.disabled = true;
            sendBtn.disabled = true;
            visualizerRing.className = "pulse-ring";
        }

        // --- Screen Sharing Loop ---
        screenBtn.addEventListener("click", async () => {
            if (screenStream) {
                stopScreenSharing();
            } else {
                await startScreenSharing();
            }
        });

        async function startScreenSharing() {
            try {
                screenStream = await navigator.mediaDevices.getDisplayMedia({
                    video: { frameRate: { ideal: 5 } },
                    audio: false
                });
                
                previewVideo.srcObject = screenStream;
                previewPlaceholder.style.display = "none";
                screenBtn.textContent = "Stop Share";
                screenBtn.className = "active";
                
                // Set up visual capture loop (1 FPS)
                const ctx = captureCanvas.getContext("2d");
                
                function getScaledSize(width, height) {
                    const MAX_SCALING_TARGETS = [
                        { width: 1024, height: 768 },
                        { width: 1280, height: 800 },
                        { width: 1366, height: 768 }
                    ];
                    let ratio = height ? width / height : 1.0;
                    for (let dim of MAX_SCALING_TARGETS) {
                        if (Math.abs((dim.width / dim.height) - ratio) < 0.02 && dim.width < width) {
                            return [dim.width, dim.height];
                        }
                    }
                    let scale = Math.min(1366 / width, 768 / height, 1.0);
                    return [Math.max(1, Math.round(width * scale)), Math.max(1, Math.round(height * scale))];
                }

                screenInterval = setInterval(() => {
                    if (ws && ws.readyState === WebSocket.OPEN && previewVideo.readyState === previewVideo.HAVE_ENOUGH_DATA) {
                        let vw = previewVideo.videoWidth;
                        let vh = previewVideo.videoHeight;
                        if (vw > 0 && vh > 0) {
                            let [out_w, out_h] = getScaledSize(vw, vh);
                            captureCanvas.width = out_w;
                            captureCanvas.height = out_h;
                            ctx.drawImage(previewVideo, 0, 0, captureCanvas.width, captureCanvas.height);
                            
                            // Export as JPEG bytes
                            captureCanvas.toBlob((blob) => {
                                if (blob && ws.readyState === WebSocket.OPEN) {
                                    ws.send(blob);
                                }
                            }, "image/jpeg", 0.6);
                        }
                    }
                }, 333);
                
                addLog("system", "Screen share active and streaming.");
            } catch (e) {
                addLog("system", `Screen Share Failed: ${e.message}`);
            }
        }

        function stopScreenSharing() {
            if (screenInterval) {
                clearInterval(screenInterval);
                screenInterval = null;
            }
            if (screenStream) {
                screenStream.getTracks().forEach(track => track.stop());
                screenStream = null;
            }
            previewVideo.srcObject = null;
            previewPlaceholder.style.display = "flex";
            screenBtn.textContent = "Share Screen";
            screenBtn.className = "";
        }

        // --- Audio Capture & Stream ---
        async function initAudio() {
            try {
                audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
                micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
                
                const source = audioContext.createMediaStreamSource(micStream);
                // ScriptProcessor is deprecated but offers high-portability for simple PCM conversions
                micProcessor = audioContext.createScriptProcessor(4096, 1, 1);
                
                source.connect(micProcessor);
                micProcessor.connect(audioContext.destination);
                
                micProcessor.onaudioprocess = (e) => {
                    if (ws && ws.readyState === WebSocket.OPEN && !isPlayingAudio && !isProcessing) {
                        const inputData = e.inputBuffer.getChannelData(0);
                        // Convert Float32 array to 16-bit signed Int16 array
                        const pcmData = new Int16Array(inputData.length);
                        for (let i = 0; i < inputData.length; i++) {
                            pcmData[i] = Math.min(1, Math.max(-1, inputData[i])) * 0x7FFF;
                        }
                        // Send binary packet
                        ws.send(pcmData.buffer);
                    }
                };
                
                visualizerRing.className = "pulse-ring listening";
                addLog("system", "Microphone capture active.");
            } catch (e) {
                addLog("system", `Microphone Access Failed: ${e.message}`);
            }
        }

        function stopAudioInput() {
            if (micProcessor) {
                micProcessor.disconnect();
                micProcessor = null;
            }
            if (micStream) {
                micStream.getTracks().forEach(track => track.stop());
                micStream = null;
            }
            if (audioContext) {
                audioContext.close();
                audioContext = null;
            }
        }

        // --- Playback audio responses ---
        async function playAudioBuffer(arrayBuffer) {
            if (!audioContext) return;
            
            try {
                // Decode synthesized WAV binary from the WebSocket
                const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
                
                isPlayingAudio = true;
                visualizerRing.className = "pulse-ring speaking";
                statusText.textContent = "Speaking";
                
                const source = audioContext.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(audioContext.destination);
                source.start(0);
                
                source.onended = () => {
                    // Add a small 600ms debounce to prevent the mic from catching the room echo
                    setTimeout(() => {
                        isPlayingAudio = false;
                        isProcessing = false;
                        visualizerRing.className = "pulse-ring listening";
                        statusText.textContent = "Connected";
                    }, 600);
                };
            } catch (e) {
                logger.error("Error decoding/playing audio:", e);
                isPlayingAudio = false;
            }
        }

        // --- Text input support ---
        sendBtn.addEventListener("click", sendTextMessage);
        textInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") sendTextMessage();
        });

        function sendTextMessage() {
            const text = textInput.value.trim();
            if (text && ws && ws.readyState === WebSocket.OPEN) {
                ws.send(json.stringify({
                    type: "text_prompt",
                    text: text
                }));
                addLog("user", text);
                textInput.value = "";
            }
        }
    