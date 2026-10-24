const SAMPLE_RATE = 16000;
const serverInput = document.querySelector("#server-url");
const connectButton = document.querySelector("#connect-button");
const recordButton = document.querySelector("#record-button");
const connectionStatus = document.querySelector("#connection-status");
const recordingLabel = document.querySelector("#recording-label");
const recordingIndicator = document.querySelector("#recording-indicator");
const errorMessage = document.querySelector("#error-message");

let mediaRecorder;
let recordingChunks = [];
let stream;
let serverUrl = localStorage.getItem("voiceLightServer") || serverInput.value;

serverInput.value = serverUrl;

function apiUrl(path) {
  return `${serverUrl.replace(/\/+$/, "")}${path}`;
}

function showError(message) {
  errorMessage.textContent = message;
}

function setConnection(connected, message) {
  connectionStatus.textContent = message;
  connectionStatus.className = connected ? "success" : "muted";
  recordButton.disabled = !connected;
}

function updateState(result) {
  document.querySelector("#transcript").textContent = result.transcript || "No speech recognized";
  document.querySelector("#command").textContent = result.command;
  document.querySelector("#response").textContent = result.message;
  const lightOn = Boolean(result.light_on);
  const relayOn = Boolean(result.relay_on);
  const statusOn = Boolean(result.status_led_on);
  document.querySelector("#light-state").classList.toggle("on", lightOn);
  document.querySelector("#light-label").textContent = lightOn ? "ON" : "OFF";
  document.querySelector("#relay-state").classList.toggle("on", relayOn);
  document.querySelector("#relay-label").textContent = relayOn ? "ON" : "OFF";
  document.querySelector("#status-led-state").classList.toggle("on", statusOn);
  document.querySelector("#status-led-label").textContent = statusOn ? "ON (unrecognized command)" : "OFF";
}

async function connect() {
  serverUrl = serverInput.value.trim().replace(/\/+$/, "");
  if (!/^https?:\/\/.+/i.test(serverUrl)) {
    setConnection(false, "Enter a valid http:// or https:// URL");
    return;
  }
  connectButton.disabled = true;
  showError("");
  try {
    const response = await fetch(apiUrl("/status"));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    updateState(await response.json());
    localStorage.setItem("voiceLightServer", serverUrl);
    setConnection(true, `Connected to ${serverUrl}`);
  } catch (error) {
    setConnection(false, "Could not connect to the Pi");
    showError(`Connection failed: ${error.message}. Check the URL and that the server is running.`);
  } finally {
    connectButton.disabled = false;
  }
}

function chooseMimeType() {
  return ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]
    .find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

async function blobToWav(blob) {
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer());
    const samples = new Float32Array(decoded.length);
    for (let channel = 0; channel < decoded.numberOfChannels; channel++) {
      const channelData = decoded.getChannelData(channel);
      for (let i = 0; i < samples.length; i++) samples[i] += channelData[i] / decoded.numberOfChannels;
    }
    const ratio = SAMPLE_RATE / decoded.sampleRate;
    const outputLength = Math.max(1, Math.round(samples.length * ratio));
    const output = new Float32Array(outputLength);
    for (let i = 0; i < outputLength; i++) {
      output[i] = samples[Math.min(samples.length - 1, Math.round(i / ratio))];
    }
    return encodeWav(output, SAMPLE_RATE);
  } finally {
    await context.close();
  }
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const write = (offset, text) => [...text].forEach((char, i) => view.setUint8(offset + i, char.charCodeAt(0)));
  write(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); write(8, "WAVE");
  write(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); write(36, "data"); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, sample < 0 ? sample * 32768 : sample * 32767, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

async function startRecording() {
  showError("");
  stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  recordingChunks = [];
  const mimeType = chooseMimeType();
  mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  mediaRecorder.ondataavailable = (event) => { if (event.data.size) recordingChunks.push(event.data); };
  mediaRecorder.onstop = sendRecording;
  mediaRecorder.start();
  recordButton.textContent = "Stop recording";
  recordButton.classList.add("stop");
  recordingIndicator.classList.add("recording");
  recordingLabel.textContent = "Recording…";
}

function stopRecording() {
  mediaRecorder.stop();
  stream.getTracks().forEach((track) => track.stop());
  recordButton.disabled = true;
  recordingLabel.textContent = "Converting audio…";
}

async function sendRecording() {
  try {
    const wav = await blobToWav(new Blob(recordingChunks));
    const response = await fetch(apiUrl("/audio"), { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav });
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${(await response.text()).slice(0, 160)}`);
    updateState(await response.json());
    recordingLabel.textContent = "Command processed";
  } catch (error) {
    showError(`Audio could not be processed: ${error.message}`);
    recordingLabel.textContent = "Ready to record";
  } finally {
    recordButton.disabled = false;
    recordButton.textContent = "Start recording";
    recordButton.classList.remove("stop");
    recordingIndicator.classList.remove("recording");
  }
}

connectButton.addEventListener("click", connect);
recordButton.addEventListener("click", () => mediaRecorder?.state === "recording" ? stopRecording() : startRecording().catch((error) => showError(`Microphone access failed: ${error.message}`)));
if (navigator.mediaDevices && window.MediaRecorder && window.AudioContext) connect();
else showError("This browser does not support microphone recording. Use a current Chrome, Edge, or Firefox browser.");
