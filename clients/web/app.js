/**
 * Vosk Raspberry Pi Voice Controller — Client Application Engine
 *
 * Implements:
 * - 16 kHz Mono 16-bit linear PCM WAV generation conforming to Vosk requirements
 * - Three voice execution modes: Push-to-Talk (Hold), Auto-Detect (VAD Silence), and Toggle
 * - Pure direct GPIO signal execution (/api/control) for 100% reliable quick actions
 * - Real-time 60fps Canvas Audio Visualizer & RMS Voice Level Meter
 * - Reverse Proxy Auto-Detection (/api) for zero-config local LAN mobile access
 * - Real-time 4-channel GPIO synchronization (Green LED, Relay, Yellow LED, Red LED)
 * - Multi-device live LAN command activity feed with client IP address tagging
 */

(function () {
  "use strict";

  // Audio Specifications required by the Raspberry Pi Vosk server
  const TARGET_SAMPLE_RATE = 16000;
  const DEFAULT_MAX_RECORD_SECONDS = 6.0;

  // DOM Elements
  const connectionPill = document.querySelector("#connection-pill");
  const connectionLabel = document.querySelector("#connection-label");
  const latencyTag = document.querySelector("#latency-tag");
  const toggleSettingsBtn = document.querySelector("#toggle-settings-btn");
  const closeSettingsBtn = document.querySelector("#close-settings-btn");
  const settingsPanel = document.querySelector("#settings-panel");
  const serverInput = document.querySelector("#server-url");
  const connectButton = document.querySelector("#connect-button");
  const vadThresholdInput = document.querySelector("#vad-threshold");
  const vadThresholdVal = document.querySelector("#vad-threshold-val");
  const silenceDelayInput = document.querySelector("#silence-delay");
  const silenceDelayVal = document.querySelector("#silence-delay-val");
  const continuousToggle = document.querySelector("#continuous-toggle");
  const secureAlert = document.querySelector("#secure-context-alert");

  // Hardware State Elements (4 Channels)
  const cardLight = document.querySelector("#card-light");
  const lightBadge = document.querySelector("#light-state-badge");
  const lightSubtext = document.querySelector("#light-subtext");

  const cardRelay = document.querySelector("#card-relay");
  const relayBadge = document.querySelector("#relay-state-badge");
  const relaySubtext = document.querySelector("#relay-subtext");

  const cardStatusLed = document.querySelector("#card-status-led");
  const statusLedBadge = document.querySelector("#status-led-badge");
  const statusLedSubtext = document.querySelector("#status-led-subtext");

  const cardRedLed = document.querySelector("#card-red-led");
  const redLedBadge = document.querySelector("#red-led-badge");
  const redLedSubtext = document.querySelector("#red-led-subtext");

  // Voice Console Elements
  const voiceConsoleCard = document.querySelector(".voice-console-card");
  const modeTabs = document.querySelectorAll(".mode-tab");
  const visualizerCanvas = document.querySelector("#audio-visualizer");
  const micButton = document.querySelector("#mic-button");
  const svgMic = document.querySelector("#svg-mic");
  const svgRecording = document.querySelector("#svg-recording");
  const svgSpinner = document.querySelector("#svg-spinner");
  const meterLevel = document.querySelector("#meter-level");
  const meterThresholdMarker = document.querySelector("#meter-threshold-marker");
  const voiceStatusTitle = document.querySelector("#voice-status-title");
  const voiceStatusHint = document.querySelector("#voice-status-hint");
  const recordTimerBadge = document.querySelector("#record-timer-badge");
  const recordDurationText = document.querySelector("#record-duration");

  // Quick Actions & Error Banner
  const quickOnBtn = document.querySelector("#quick-on-btn");
  const quickOffBtn = document.querySelector("#quick-off-btn");
  const quickSyncBtn = document.querySelector("#quick-sync-btn");
  const errorBanner = document.querySelector("#error-banner");
  const errorMessageText = document.querySelector("#error-message-text");
  const dismissErrorBtn = document.querySelector("#dismiss-error-btn");

  // Results & History
  const transcriptText = document.querySelector("#transcript-text");
  const commandBadge = document.querySelector("#command-badge");
  const responseText = document.querySelector("#response-text");
  const executionTimeTag = document.querySelector("#execution-time-tag");
  const historyList = document.querySelector("#history-list");
  const clearHistoryBtn = document.querySelector("#clear-history-btn");

  // Canvas visualizer context
  const canvasCtx = visualizerCanvas ? visualizerCanvas.getContext("2d") : null;

  // Application State
  let currentMode = "ptt"; // "ptt" | "vad" | "toggle"
  let isConnected = false;
  let useProxy = false;
  let serverBaseUrl = localStorage.getItem("voskPiServerUrl") || serverInput.value;
  let vadThreshold = parseFloat(vadThresholdInput.value) || 0.03;
  let silenceDuration = parseFloat(silenceDelayInput.value) || 0.8;
  let isContinuous = false;

  // Web Audio Context & Nodes
  let audioContext = null;
  let mediaStream = null;
  let sourceNode = null;
  let analyserNode = null;
  let processorNode = null;

  // Audio Recording Buffers
  let pcmChunks = [];
  let isRecording = false;
  let isListening = false;
  let isProcessing = false;
  let speechDetected = false;
  let recordStartTime = 0;
  let recordTimerInterval = null;
  let silenceTimer = 0;
  let pressStartTime = 0;
  let statusPollInterval = null;
  let historyPollInterval = null;

  // Visualizer Animation Frame
  let visualizerAnimFrame = null;

  /**
   * Helper to format API endpoints depending on whether laptop proxy is available.
   */
  function getApiEndpoint(path) {
    if (useProxy) {
      return `/api${path}`;
    }
    return `${serverBaseUrl.replace(/\/+$/, "")}${path}`;
  }

  function showError(msg) {
    if (!msg) {
      errorBanner.classList.add("hidden");
      return;
    }
    errorMessageText.textContent = msg;
    errorBanner.classList.remove("hidden");
  }

  function setStatusMessage(title, hint) {
    if (title) voiceStatusTitle.textContent = title;
    if (hint !== undefined) voiceStatusHint.textContent = hint;
  }

  function setButtonState(state) {
    voiceConsoleCard.classList.remove("listening", "recording", "processing");
    svgMic.classList.add("hidden");
    svgRecording.classList.add("hidden");
    svgSpinner.classList.add("hidden");

    if (state === "recording") {
      voiceConsoleCard.classList.add("recording");
      svgRecording.classList.remove("hidden");
      recordTimerBadge.classList.remove("hidden");
    } else if (state === "listening") {
      voiceConsoleCard.classList.add("listening");
      svgMic.classList.remove("hidden");
      recordTimerBadge.classList.add("hidden");
    } else if (state === "processing") {
      voiceConsoleCard.classList.add("processing");
      svgSpinner.classList.remove("hidden");
      recordTimerBadge.classList.add("hidden");
    } else {
      svgMic.classList.remove("hidden");
      recordTimerBadge.classList.add("hidden");
    }
  }

  function updateHardwareHUD(data) {
    if (!data) return;

    const lightOn = Boolean(data.light_on);
    const relayOn = Boolean(data.relay_on);
    const yellowOn = Boolean(data.yellow_led_on || data.status_led_on);
    const redOn = Boolean(data.red_led_on);

    // Green LED (GPIO 22)
    if (cardLight && lightBadge) {
      cardLight.classList.toggle("active-light", lightOn);
      lightBadge.textContent = lightOn ? "ON" : "OFF";
      lightBadge.className = `state-pill ${lightOn ? "state-on" : "state-off"}`;
      if (lightSubtext) lightSubtext.textContent = lightOn ? "Active / Illuminating" : "Standby";
    }

    // 12V Relay Module (GPIO 23)
    if (cardRelay && relayBadge) {
      cardRelay.classList.toggle("active-relay", relayOn);
      relayBadge.textContent = relayOn ? "ON" : "OFF";
      relayBadge.className = `state-pill ${relayOn ? "state-relay-on" : "state-off"}`;
      if (relaySubtext) relaySubtext.textContent = relayOn ? "Energized / Closed" : "Contacts Open";
    }

    // Status Yellow LED (GPIO 27)
    if (cardStatusLed && statusLedBadge) {
      cardStatusLed.classList.toggle("active-status", yellowOn);
      statusLedBadge.textContent = yellowOn ? "ALERT" : "IDLE";
      statusLedBadge.className = `state-pill ${yellowOn ? "state-alert" : "state-idle"}`;
      if (statusLedSubtext) statusLedSubtext.textContent = yellowOn ? "Unrecognized Command" : "Normal";
    }

    // Red Error LED (GPIO 17)
    if (cardRedLed && redLedBadge) {
      cardRedLed.classList.toggle("active-status", redOn);
      redLedBadge.textContent = redOn ? "ALERT" : "OFF";
      redLedBadge.className = `state-pill ${redOn ? "state-alert" : "state-off"}`;
      if (redLedSubtext) redLedSubtext.textContent = redOn ? "Error Alert" : "Normal";
    }
  }

  function updateResult(result, latencyMs) {
    transcriptText.textContent = result.transcript || "(No speech detected)";
    responseText.textContent = result.message || "Ready";

    const cmd = (result.command || "UNKNOWN").toUpperCase();
    commandBadge.textContent = cmd;
    commandBadge.className = "action-badge";

    if (cmd === "ON") {
      commandBadge.classList.add("badge-on");
    } else if (cmd === "OFF") {
      commandBadge.classList.add("badge-off");
    } else {
      commandBadge.classList.add("badge-unknown");
    }

    if (latencyMs) {
      executionTimeTag.textContent = `${latencyMs}ms`;
    }
  }

  /**
   * Multi-Device Activity Log
   * Receives commands executed across all connected phones and computers with their IP tags.
   */
  async function pollMultiDeviceHistory() {
    try {
      const res = await fetch(getApiEndpoint("/history"), { signal: AbortSignal.timeout(2500) });
      if (res.ok) {
        const items = await res.json();
        renderMultiDeviceHistory(items);
      }
    } catch (_) {}
  }

  function renderMultiDeviceHistory(items) {
    if (!items || !items.length) {
      historyList.innerHTML = '<li class="history-empty">No commands executed yet from local devices.</li>';
      return;
    }

    historyList.innerHTML = items.map(item => {
      let typeClass = "type-voice";
      let typeLabel = "VOICE";
      if (item.type === "DIRECT_GPIO") {
        typeClass = "type-gpio";
        typeLabel = "DIRECT GPIO";
      } else if (item.type === "PIN_TEST") {
        typeClass = "type-test";
        typeLabel = "PIN TEST";
      }

      let cmdClass = item.command === "ON" ? "badge-on" : item.command === "OFF" ? "badge-off" : "badge-unknown";

      return `
        <li class="history-item">
          <div class="history-item-left">
            <span class="ip-badge" title="Source Device IP">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
              ${item.client_ip || "Local Device"}
            </span>
            <span class="type-badge ${typeClass}">${typeLabel}</span>
            <span class="action-badge ${cmdClass}" style="font-size:0.72rem; padding: 2px 7px;">${item.command}</span>
            <span class="history-transcript" title="${item.transcript}">“${item.transcript}”</span>
          </div>
          <span class="history-time">${item.time}</span>
        </li>
      `;
    }).join("");
  }

  /**
   * Resampling and WAV Encoding
   * Converts Float32Array PCM samples at source sample rate to strictly
   * 16,000 Hz, 1-channel, 16-bit linear PCM WAV format.
   */
  function encodeWav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    const writeString = (offset, string) => {
      for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
      }
    };

    // RIFF chunk descriptor
    writeString(0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(8, "WAVE");

    // fmt sub-chunk (16-bit PCM)
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);

    // data sub-chunk
    writeString(36, "data");
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }

    return new Blob([buffer], { type: "audio/wav" });
  }

  function resampleAudioBuffer(rawChunks, sourceSampleRate, targetSampleRate) {
    let totalLength = 0;
    for (let chunk of rawChunks) totalLength += chunk.length;
    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (let chunk of rawChunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }

    if (sourceSampleRate === targetSampleRate) {
      return merged;
    }

    const ratio = sourceSampleRate / targetSampleRate;
    const newLength = Math.round(totalLength / ratio);
    const result = new Float32Array(newLength);

    for (let i = 0; i < newLength; i++) {
      const srcIndex = i * ratio;
      const index = Math.floor(srcIndex);
      const nextIndex = Math.min(index + 1, totalLength - 1);
      const weight = srcIndex - index;
      result[i] = merged[index] * (1 - weight) + merged[nextIndex] * weight;
    }

    return result;
  }

  /**
   * Initializes Web Audio context and microphone capture stream.
   */
  async function initAudioEngine() {
    if (audioContext && mediaStream) {
      if (audioContext.state === "suspended") {
        await audioContext.resume();
      }
      return true;
    }

    try {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) {
        throw new Error("Web Audio API is not supported in this browser.");
      }

      audioContext = new AudioContextClass();
      if (audioContext.state === "suspended") {
        await audioContext.resume();
      }

      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      sourceNode = audioContext.createMediaStreamSource(mediaStream);
      analyserNode = audioContext.createAnalyser();
      analyserNode.fftSize = 256;
      analyserNode.smoothingTimeConstant = 0.6;
      sourceNode.connect(analyserNode);

      processorNode = audioContext.createScriptProcessor(2048, 1, 1);
      processorNode.onaudioprocess = handleAudioProcess;
      sourceNode.connect(processorNode);
      processorNode.connect(audioContext.destination);

      startVisualizer();
      return true;
    } catch (err) {
      showError(`Microphone access failed: ${err.message}. If accessing from another device, use HTTPS or check browser permissions.`);
      return false;
    }
  }

  function handleAudioProcess(event) {
    const input = event.inputBuffer.getChannelData(0);

    let sum = 0;
    for (let i = 0; i < input.length; i++) {
      sum += input[i] * input[i];
    }
    const rms = Math.sqrt(sum / input.length);

    const meterPct = Math.min(100, Math.round((rms / 0.15) * 100));
    meterLevel.style.width = `${meterPct}%`;

    if (isRecording) {
      pcmChunks.push(new Float32Array(input));

      if (currentMode === "vad") {
        const frameDuration = input.length / audioContext.sampleRate;
        if (rms >= vadThreshold) {
          speechDetected = true;
          silenceTimer = 0;
          setStatusMessage("Speech detected! Recording...", "Pause to automatically submit");
        } else if (speechDetected) {
          silenceTimer += frameDuration;
          if (silenceTimer >= silenceDuration) {
            stopAndSendAudio();
          }
        }
      }
    } else if (isListening && currentMode === "vad") {
      if (rms >= vadThreshold) {
        startRecordingChunk();
        speechDetected = true;
        silenceTimer = 0;
        setStatusMessage("Speech detected! Recording...", "Pause to automatically submit");
      }
    }
  }

  function startVisualizer() {
    if (!visualizerCanvas || !canvasCtx || !analyserNode) return;
    const bufferLength = analyserNode.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    function draw() {
      visualizerAnimFrame = requestAnimationFrame(draw);
      analyserNode.getByteFrequencyData(dataArray);

      const width = visualizerCanvas.width;
      const height = visualizerCanvas.height;
      canvasCtx.clearRect(0, 0, width, height);

      const barCount = 36;
      const barWidth = 6;
      const gap = 6;
      const totalWidth = barCount * (barWidth + gap);
      const startX = (width - totalWidth) / 2;

      for (let i = 0; i < barCount; i++) {
        const dataIndex = Math.floor((i / barCount) * (bufferLength / 2));
        const val = dataArray[dataIndex] || 0;
        const normalized = val / 255;

        let barHeight = Math.max(4, normalized * (height * 0.7));
        if (!isRecording && !isListening) {
          barHeight = 4;
        }

        const x = startX + i * (barWidth + gap);
        const y = (height - barHeight) / 2;

        const gradient = canvasCtx.createLinearGradient(0, y, 0, y + barHeight);
        if (isRecording) {
          gradient.addColorStop(0, "#ef4444");
          gradient.addColorStop(1, "#f97316");
        } else if (isListening) {
          gradient.addColorStop(0, "#38bdf8");
          gradient.addColorStop(1, "#10b981");
        } else {
          gradient.addColorStop(0, "rgba(59, 130, 246, 0.4)");
          gradient.addColorStop(1, "rgba(6, 182, 212, 0.2)");
        }

        canvasCtx.fillStyle = gradient;
        canvasCtx.beginPath();
        canvasCtx.roundRect(x, y, barWidth, barHeight, 3);
        canvasCtx.fill();
      }
    }

    draw();
  }

  function startRecordingChunk() {
    pcmChunks = [];
    isRecording = true;
    speechDetected = false;
    silenceTimer = 0;
    recordStartTime = Date.now();

    setButtonState("recording");
    if (navigator.vibrate) navigator.vibrate(40);

    clearInterval(recordTimerInterval);
    recordTimerInterval = setInterval(() => {
      const elapsed = ((Date.now() - recordStartTime) / 1000).toFixed(1);
      recordDurationText.textContent = `${elapsed}s`;

      if (elapsed >= DEFAULT_MAX_RECORD_SECONDS) {
        stopAndSendAudio();
      }
    }, 100);
  }

  async function stopAndSendAudio() {
    if (!isRecording && !isListening) return;

    clearInterval(recordTimerInterval);
    isRecording = false;
    setButtonState("processing");
    setStatusMessage("Transcribing with Vosk model on Pi...", "Processing WAV audio");

    if (pcmChunks.length === 0) {
      resetVoiceState();
      return;
    }

    try {
      const sourceSampleRate = audioContext ? audioContext.sampleRate : 48000;
      const resampledSamples = resampleAudioBuffer(pcmChunks, sourceSampleRate, TARGET_SAMPLE_RATE);
      const wavBlob = encodeWav(resampledSamples, TARGET_SAMPLE_RATE);

      const startTime = Date.now();
      const response = await fetch(getApiEndpoint("/audio"), {
        method: "POST",
        headers: { "Content-Type": "audio/wav" },
        body: wavBlob,
      });

      const latency = Date.now() - startTime;
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Server returned HTTP ${response.status}: ${errorText.slice(0, 100)}`);
      }

      const result = await response.json();
      updateResult(result, latency);
      updateHardwareHUD(result);
      pollMultiDeviceHistory();

      if (navigator.vibrate) navigator.vibrate([30, 40, 30]);
      setStatusMessage("Command Executed!", `“${result.transcript}” → ${result.command}`);
    } catch (err) {
      showError(`Voice command failed: ${err.message}`);
      setStatusMessage("Recognition Failed", err.message);
    } finally {
      pcmChunks = [];
      resetVoiceState();
    }
  }

  function resetVoiceState() {
    isRecording = false;
    isProcessing = false;
    clearInterval(recordTimerInterval);

    if (currentMode === "vad" && isContinuous) {
      isListening = true;
      setButtonState("listening");
      setStatusMessage("Listening for speech...", "Say 'turn on the light' or 'turn off the light'");
    } else {
      isListening = false;
      setButtonState("idle");
      updatePromptForCurrentMode();
    }
  }

  function updatePromptForCurrentMode() {
    if (currentMode === "ptt") {
      setStatusMessage("Ready (Push-to-Talk)", "Press & hold button or Spacebar while speaking");
    } else if (currentMode === "vad") {
      setStatusMessage("Auto-Detect Ready", "Tap microphone to start listening");
    } else {
      setStatusMessage("Toggle Mode", "Tap button to start, tap again to finish");
    }
  }

  /**
   * Connect and Health Check
   */
  async function connectToServer() {
    showError("");
    connectionPill.className = "connection-pill connecting";
    connectionLabel.textContent = "Connecting...";

    try {
      const proxyCheck = await fetch("/api/status", { signal: AbortSignal.timeout(2500) });
      if (proxyCheck.ok) {
        useProxy = true;
        const data = await proxyCheck.json();
        handleSuccessfulConnection(data, "Connected via Laptop Proxy");
        return;
      }
    } catch (_) {
      useProxy = false;
    }

    serverBaseUrl = serverInput.value.trim().replace(/\/+$/, "");
    if (!/^https?:\/\/.+/i.test(serverBaseUrl)) {
      connectionPill.className = "connection-pill disconnected";
      connectionLabel.textContent = "Invalid URL";
      showError("Enter a valid Pi URL starting with http:// or https://");
      return;
    }

    try {
      const startTime = Date.now();
      const response = await fetch(`${serverBaseUrl}/status`, { signal: AbortSignal.timeout(4000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const latency = Date.now() - startTime;
      latencyTag.textContent = `${latency}ms`;
      latencyTag.classList.remove("hidden");
      handleSuccessfulConnection(data, `Connected to ${serverBaseUrl}`);
    } catch (err) {
      connectionPill.className = "connection-pill disconnected";
      connectionLabel.textContent = "Disconnected";
      latencyTag.classList.add("hidden");
      showError(`Could not reach Pi server: ${err.message}. Ensure the Pi server is running on the network.`);
    }
  }

  function handleSuccessfulConnection(data, label) {
    isConnected = true;
    micButton.disabled = false;
    connectionPill.className = "connection-pill connected";
    connectionLabel.textContent = label;
    localStorage.setItem("voskPiServerUrl", serverBaseUrl);
    updateHardwareHUD(data);
    updatePromptForCurrentMode();

    if (!statusPollInterval) {
      statusPollInterval = setInterval(pollServerStatus, 3500);
    }
    if (!historyPollInterval) {
      pollMultiDeviceHistory();
      historyPollInterval = setInterval(pollMultiDeviceHistory, 2000);
    }
  }

  async function pollServerStatus() {
    if (!isConnected || isRecording || isProcessing) return;
    try {
      const res = await fetch(getApiEndpoint("/status"), { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        const data = await res.json();
        updateHardwareHUD(data);
      }
    } catch (_) {}
  }

  /**
   * Pure Direct GPIO Signal Execution
   * Gives an immediate, deterministic electrical signal directly to the GPIO pins,
   * completely separate from Vosk speech recognition.
   */
  async function sendDirectSignal(command) {
    showError("");
    setButtonState("processing");
    setStatusMessage(`Sending Pure GPIO Signal (${command})...`, "Direct electrical signal to pins");

    try {
      const startTime = Date.now();
      const endpoint = getApiEndpoint("/control");
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
      });

      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }

      const data = await res.json();
      const latency = Date.now() - startTime;
      updateResult(data, latency);
      updateHardwareHUD(data);
      pollMultiDeviceHistory();
      setStatusMessage("Direct GPIO Signal Executed", data.message);
    } catch (err) {
      showError(`Direct GPIO command failed: ${err.message}`);
    } finally {
      resetVoiceState();
    }
  }

  /**
   * Event Listeners Setup
   */
  function setupEventListeners() {
    modeTabs.forEach(tab => {
      tab.addEventListener("click", () => {
        modeTabs.forEach(t => {
          t.classList.remove("active");
          t.setAttribute("aria-selected", "false");
        });
        tab.classList.add("active");
        tab.setAttribute("aria-selected", "true");
        currentMode = tab.dataset.mode;
        resetVoiceState();
        updatePromptForCurrentMode();
      });
    });

    micButton.addEventListener("pointerdown", async (e) => {
      e.preventDefault();
      if (!isConnected || isProcessing) return;

      const audioOk = await initAudioEngine();
      if (!audioOk) return;

      if (currentMode === "ptt") {
        pressStartTime = Date.now();
        micButton.classList.add("is-held");
        startRecordingChunk();
        setStatusMessage("Recording... (Hold to Speak)", "Release button when done");
      }
    });

    const releasePTT = () => {
      if (currentMode === "ptt" && isRecording) {
        micButton.classList.remove("is-held");
        const duration = Date.now() - pressStartTime;
        if (duration < 250) {
          resetVoiceState();
          showError("Press and hold the button while speaking a command.");
          return;
        }
        stopAndSendAudio();
      }
    };

    window.addEventListener("pointerup", releasePTT);
    window.addEventListener("pointercancel", releasePTT);

    window.addEventListener("keydown", async (e) => {
      if (e.code === "Space" && currentMode === "ptt" && !e.repeat) {
        const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : "";
        if (activeTag === "input" || activeTag === "textarea") return;

        e.preventDefault();
        const audioOk = await initAudioEngine();
        if (!audioOk || isRecording || isProcessing) return;

        pressStartTime = Date.now();
        micButton.classList.add("is-held");
        startRecordingChunk();
        setStatusMessage("Recording... (Spacebar Held)", "Release Spacebar to send command");
      }
    });

    window.addEventListener("keyup", (e) => {
      if (e.code === "Space" && currentMode === "ptt" && isRecording) {
        const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : "";
        if (activeTag === "input" || activeTag === "textarea") return;

        e.preventDefault();
        releasePTT();
      }
    });

    micButton.addEventListener("click", async () => {
      if (!isConnected || isProcessing) return;
      if (currentMode === "ptt") return;

      const audioOk = await initAudioEngine();
      if (!audioOk) return;

      if (currentMode === "vad") {
        if (isListening || isRecording) {
          resetVoiceState();
          setStatusMessage("Auto-Detect Stopped", "Tap microphone to resume listening");
        } else {
          isListening = true;
          setButtonState("listening");
          setStatusMessage("Listening for speech...", "Say 'turn on the light' or 'turn off the light'");
        }
      } else if (currentMode === "toggle") {
        if (isRecording) {
          stopAndSendAudio();
        } else {
          startRecordingChunk();
          setStatusMessage("Recording Audio...", "Tap again to finish & send");
        }
      }
    });

    // Pure Direct GPIO Quick Action buttons (bypasses Vosk completely)
    quickOnBtn.addEventListener("click", () => sendDirectSignal("ON"));
    quickOffBtn.addEventListener("click", () => sendDirectSignal("OFF"));
    quickSyncBtn.addEventListener("click", () => {
      pollServerStatus();
      pollMultiDeviceHistory();
    });

    toggleSettingsBtn.addEventListener("click", () => settingsPanel.classList.toggle("hidden"));
    closeSettingsBtn.addEventListener("click", () => settingsPanel.classList.add("hidden"));
    connectionPill.addEventListener("click", () => settingsPanel.classList.toggle("hidden"));
    connectButton.addEventListener("click", connectToServer);

    vadThresholdInput.addEventListener("input", (e) => {
      vadThreshold = parseFloat(e.target.value);
      vadThresholdVal.textContent = vadThreshold.toFixed(3);
      meterThresholdMarker.style.left = `${Math.min(100, Math.round((vadThreshold / 0.15) * 100))}%`;
    });

    silenceDelayInput.addEventListener("input", (e) => {
      silenceDuration = parseFloat(e.target.value);
      silenceDelayVal.textContent = `${silenceDuration.toFixed(1)}s`;
    });

    continuousToggle.addEventListener("change", (e) => {
      isContinuous = e.target.checked;
    });

    dismissErrorBtn.addEventListener("click", () => showError(""));
    clearHistoryBtn.addEventListener("click", async () => {
      try {
        await fetch(getApiEndpoint("/history"), { method: "DELETE" });
        renderMultiDeviceHistory([]);
      } catch (_) {}
    });

    // Help Modal Window Handlers
    const openHelpModalBtn = document.querySelector("#open-help-modal-btn");
    const closeHelpModalBtn = document.querySelector("#close-help-modal-btn");
    const helpModal = document.querySelector("#help-modal");

    if (openHelpModalBtn && helpModal) {
      openHelpModalBtn.addEventListener("click", () => {
        helpModal.classList.remove("hidden");
      });
    }

    if (closeHelpModalBtn && helpModal) {
      closeHelpModalBtn.addEventListener("click", () => {
        helpModal.classList.add("hidden");
      });
    }

    if (helpModal) {
      helpModal.addEventListener("click", (e) => {
        if (e.target === helpModal) {
          helpModal.classList.add("hidden");
        }
      });
      window.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !helpModal.classList.contains("hidden")) {
          helpModal.classList.add("hidden");
        }
      });
    }

    // Example Chips in Help Window
    document.querySelectorAll(".example-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        const phrase = chip.dataset.phrase || chip.textContent.replace(/[“”"]/g, "").trim();
        if (navigator.clipboard) {
          navigator.clipboard.writeText(phrase).catch(() => {});
        }
        setStatusMessage(null, `Try saying: “${phrase}”`);
        const originalText = chip.textContent;
        chip.textContent = "Copied ✓";
        setTimeout(() => { chip.textContent = originalText; }, 1200);
      });
    });

    if (window.isSecureContext === false && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
      secureAlert.classList.remove("hidden");
    }
  }

  // Initialization
  setupEventListeners();
  serverInput.value = serverBaseUrl;
  connectToServer();

})();
