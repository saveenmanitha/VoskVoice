/**
 * Vosk Raspberry Pi Voice Controller — Hardware Diagnostics Engine
 * Controls independent GPIO pins (3 LEDs & 1 Relay) and syncs multi-device activity.
 */

(function () {
  "use strict";

  const connectionPill = document.querySelector("#connection-pill");
  const connectionLabel = document.querySelector("#connection-label");
  const latencyTag = document.querySelector("#latency-tag");

  // Cards & Toggles
  const cardGreen = document.querySelector("#diag-card-green");
  const toggleGreen = document.querySelector("#toggle-green");
  const labelGreen = document.querySelector("#label-green");

  const cardRelay = document.querySelector("#diag-card-relay");
  const toggleRelay = document.querySelector("#toggle-relay");
  const labelRelay = document.querySelector("#label-relay");

  const cardYellow = document.querySelector("#diag-card-yellow");
  const toggleYellow = document.querySelector("#toggle-yellow");
  const labelYellow = document.querySelector("#label-yellow");

  const cardRed = document.querySelector("#diag-card-red");
  const toggleRed = document.querySelector("#toggle-red");
  const labelRed = document.querySelector("#label-red");

  // Master buttons
  const masterAllOnBtn = document.querySelector("#master-all-on-btn");
  const masterAllOffBtn = document.querySelector("#master-all-off-btn");
  const masterCycleBtn = document.querySelector("#master-cycle-btn");

  // Multi-Device History
  const historyList = document.querySelector("#multi-device-history-list");
  const clearHistoryBtn = document.querySelector("#clear-history-btn");

  let isConnected = false;
  let useProxy = true; // Default to laptop proxy
  let serverBaseUrl = localStorage.getItem("voskPiServerUrl") || "http://raspberrypi.local:8765";
  let isCycling = false;

  function getApiEndpoint(path) {
    if (useProxy) {
      return `/api${path}`;
    }
    return `${serverBaseUrl.replace(/\/+$/, "")}${path}`;
  }

  function updateHUD(data) {
    if (!data) return;

    const greenOn = Boolean(data.light_on);
    const relayOn = Boolean(data.relay_on);
    const yellowOn = Boolean(data.yellow_led_on || data.status_led_on);
    const redOn = Boolean(data.red_led_on);

    // Green
    toggleGreen.checked = greenOn;
    cardGreen.classList.toggle("active-light", greenOn);
    labelGreen.textContent = greenOn ? "ON" : "OFF";
    labelGreen.className = `state-pill ${greenOn ? "state-on" : "state-off"}`;

    // Relay
    toggleRelay.checked = relayOn;
    cardRelay.classList.toggle("active-relay", relayOn);
    labelRelay.textContent = relayOn ? "ENERGIZED" : "OPEN";
    labelRelay.className = `state-pill ${relayOn ? "state-relay-on" : "state-off"}`;

    // Yellow
    toggleYellow.checked = yellowOn;
    cardYellow.classList.toggle("active-status", yellowOn);
    labelYellow.textContent = yellowOn ? "ON" : "OFF";
    labelYellow.className = `state-pill ${yellowOn ? "state-alert" : "state-idle"}`;

    // Red
    toggleRed.checked = redOn;
    cardRed.classList.toggle("active-status", redOn);
    labelRed.textContent = redOn ? "ON" : "OFF";
    labelRed.className = `state-pill ${redOn ? "state-alert" : "state-off"}`;
  }

  async function setPin(component, state) {
    try {
      const res = await fetch(getApiEndpoint("/gpio"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ component, state }),
      });
      if (res.ok) {
        const data = await res.json();
        updateHUD(data);
        pollHistory();
      }
    } catch (err) {
      console.error("Failed to set pin:", err);
    }
  }

  async function pollStatus() {
    try {
      const start = Date.now();
      const res = await fetch(getApiEndpoint("/status"), { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        const data = await res.json();
        const latency = Date.now() - start;
        latencyTag.textContent = `${latency}ms`;
        latencyTag.classList.remove("hidden");
        connectionPill.className = "connection-pill connected";
        connectionLabel.textContent = "Connected (Pi Hardware)";
        isConnected = true;
        updateHUD(data);
      }
    } catch (_) {
      connectionPill.className = "connection-pill disconnected";
      connectionLabel.textContent = "Disconnected";
      latencyTag.classList.add("hidden");
      isConnected = false;
    }
  }

  async function pollHistory() {
    try {
      const res = await fetch(getApiEndpoint("/history"), { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        const history = await res.json();
        renderHistory(history);
      }
    } catch (_) {}
  }

  function renderHistory(items) {
    if (!items || !items.length) {
      historyList.innerHTML = '<li class="history-empty">No commands received from local devices yet.</li>';
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

  // Toggle switch listeners
  toggleGreen.addEventListener("change", (e) => setPin("green", e.target.checked));
  toggleRelay.addEventListener("change", (e) => setPin("relay", e.target.checked));
  toggleYellow.addEventListener("change", (e) => setPin("yellow", e.target.checked));
  toggleRed.addEventListener("change", (e) => setPin("red", e.target.checked));

  // Pulse & Blink Test buttons
  document.querySelectorAll(".pulse-test-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const pin = btn.dataset.pin;
      const action = btn.dataset.action;
      btn.disabled = true;

      if (action === "pulse") {
        await setPin(pin, true);
        setTimeout(async () => {
          await setPin(pin, false);
          btn.disabled = false;
        }, 1000);
      } else if (action === "blink") {
        // Blink 3 times
        for (let i = 0; i < 3; i++) {
          await setPin(pin, true);
          await new Promise(r => setTimeout(r, 250));
          await setPin(pin, false);
          await new Promise(r => setTimeout(r, 200));
        }
        btn.disabled = false;
      }
    });
  });

  // Master Controls
  masterAllOnBtn.addEventListener("click", () => setPin("all", true));
  masterAllOffBtn.addEventListener("click", () => setPin("all", false));

  masterCycleBtn.addEventListener("click", async () => {
    if (isCycling) return;
    isCycling = true;
    masterCycleBtn.disabled = true;

    // Turn all off first
    await setPin("all", false);
    await new Promise(r => setTimeout(r, 300));

    const sequence = ["green", "relay", "yellow", "red"];
    for (const comp of sequence) {
      await setPin(comp, true);
      await new Promise(r => setTimeout(r, 650));
      await setPin(comp, false);
      await new Promise(r => setTimeout(r, 250));
    }

    isCycling = false;
    masterCycleBtn.disabled = false;
  });

  // Clear History
  clearHistoryBtn.addEventListener("click", async () => {
    try {
      await fetch(getApiEndpoint("/history"), { method: "DELETE" });
      renderHistory([]);
    } catch (_) {}
  });

  // Initial connect & poll loops
  pollStatus();
  pollHistory();
  setInterval(pollStatus, 3000);
  setInterval(pollHistory, 2000);

})();
