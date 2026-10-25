// Curiosity Pet iPad page: microphone -> WebSocket -> server; the server sends back text and audio sentence by sentence, and this page plays and highlights them.
// Loads no external resources. See server.py for the protocol.
//
// One button does everything: tap to start (microphone permission, connect, listen), tap again to stop
// (the server cancels any running answer, forgets the conversation and goes idle). The VAD decides when the
// child has finished speaking, so there is no push-to-talk.
"use strict";

const TTS_RATE = 24000;

// UI strings (zh / EN). Covers buttons and prompts only; the pet's answer language still follows the language of the child's question
const STRINGS = {
  zh: {
    status: { off: "点一下开始", connecting: "正在连接...", listening: "我在听,说吧", thinking: "让我想一想", speaking: "", ended: "下次见!" },
    start: "开始", stop: "停止", ask: "打字提问", send: "发送",
    micDenied: "需要麦克风权限:请让大人在设置里打开",
    source: (t) => `资料来源:${t}`,
    toggle: "EN", toggleLabel: "Switch to English",
    chooseSkin: "选一个伙伴",
  },
  en: {
    status: { off: "Tap to start", connecting: "Connecting...", listening: "I'm listening!", thinking: "Let me think", speaking: "", ended: "See you next time!" },
    start: "Start", stop: "Stop", ask: "Type a question", send: "Send",
    micDenied: "Microphone access is needed: ask a grown-up to turn it on in Settings",
    source: (t) => `Source: ${t}`,
    toggle: "中", toggleLabel: "切换到中文",
    chooseSkin: "Choose a buddy",
  },
};

function savedLang() {
  try {
    const v = localStorage.getItem("uiLang");
    if (v === "zh" || v === "en") return v;
  } catch (e) { /* storage is unavailable in private mode etc.; use the default */ }
  return (navigator.language || "zh").toLowerCase().startsWith("zh") ? "zh" : "en";
}
let uiLang = savedLang();
const T = () => STRINGS[uiLang];

const app = document.getElementById("app");
const statusEl = document.getElementById("status");
const heardEl = document.getElementById("heard");
const answerEl = document.getElementById("answer");
const micBtn = document.getElementById("mic");
const micLabel = micBtn.querySelector(".mic-label");

let ctx = null;          // AudioContext, must be created inside a tap (iOS restriction)
let ws = null;
let state = "off";       // off | connecting | listening | thinking | speaking | ended
let started = false;     // microphone and socket are set up
let playEnd = 0;         // end time of the audio queued so far
let pending = 0;         // number of sentences not yet finished playing
let turnDone = false;    // server has finished sending this turn
const sources = new Set(); // audio playing or queued, so it can be stopped at the end
let heardLang = "zh";

const ACTIVE = new Set(["listening", "thinking", "speaking"]);

function setState(s) {
  state = s;
  app.dataset.state = s;
  updateSkin(s);
  statusEl.textContent = T().status[s] ?? "";
  micBtn.disabled = s === "connecting";
  micLabel.textContent = ACTIVE.has(s) ? T().stop : T().start;
}

// Play a cue sound locally as soon as the VAD decides the child has finished, without waiting for the server.
// Each buddy has its own: the kitten meows (synthesized here), a skin plays /cue.wav (its own recording, or its
// catchphrase in its voice, e.g. Goku "嘿!", Pikachu "皮卡!"), decoded once so it starts instantly.
let cueUrl = null;   // null: the built-in kitten
let cueBuf = null;   // the skin's decoded cue

async function loadCue() {
  cueBuf = null;
  if (!cueUrl || !ctx) return;
  try {
    const r = await fetch(`${cueUrl}?lang=${uiLang}`, { cache: "no-cache" });
    if (r.ok) cueBuf = await ctx.decodeAudioData(await r.arrayBuffer());
  } catch (e) { cueBuf = null; /* fall back to the chime */ }
}

function playCue() {
  if (!ctx) return;
  if (cueBuf) {
    const s = ctx.createBufferSource();
    s.buffer = cueBuf;
    s.connect(ctx.destination);
    s.start();
  } else if (cueUrl) {
    playChime();  // a skin whose cue could not be loaded: a neutral "ding", never a meow
  } else {
    playMeow();
  }
}

// Two soft sine notes
function playChime() {
  const t = ctx.currentTime;
  [[880, 0], [1320, 0.12]].forEach(([f, d]) => {
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = "sine";
    o.frequency.value = f;
    g.gain.setValueAtTime(0, t + d);
    g.gain.linearRampToValueAtTime(0.2, t + d + 0.02);
    g.gain.exponentialRampToValueAtTime(0.001, t + d + 0.3);
    o.connect(g).connect(ctx.destination);
    o.start(t + d);
    o.stop(t + d + 0.32);
  });
}

// The kitten's "meow": a sawtooth wave through a band-pass filter, pitch rising then falling, about 0.35 seconds, with no recorded samples
function playMeow() {
  const t = ctx.currentTime;
  const o = ctx.createOscillator();
  const bp = ctx.createBiquadFilter();
  const g = ctx.createGain();
  o.type = "sawtooth";
  o.frequency.setValueAtTime(520, t);
  o.frequency.linearRampToValueAtTime(820, t + 0.12);
  o.frequency.linearRampToValueAtTime(600, t + 0.34);
  bp.type = "bandpass";
  bp.Q.value = 4;
  bp.frequency.setValueAtTime(900, t);
  bp.frequency.linearRampToValueAtTime(1600, t + 0.12);
  bp.frequency.linearRampToValueAtTime(1100, t + 0.34);
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(0.25, t + 0.04);
  g.gain.setValueAtTime(0.25, t + 0.2);
  g.gain.linearRampToValueAtTime(0, t + 0.35);
  o.connect(bp).connect(g).connect(ctx.destination);
  o.start(t);
  o.stop(t + 0.36);
}

function addSentence(id, text) {
  const span = document.createElement("span");
  span.id = "s" + id;
  span.className = "later";
  // English sentences need a space between them; Chinese does not
  span.textContent = /[A-Za-z.!?,]$/.test(text) ? text + " " : text;
  answerEl.appendChild(span);
}

function playSentence(buf) {
  const view = new DataView(buf);
  const id = view.getUint32(0, true);
  const pcm = new Int16Array(buf, 4);
  const audio = ctx.createBuffer(1, pcm.length, TTS_RATE);
  const ch = audio.getChannelData(0);
  for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;

  const src = ctx.createBufferSource();
  src.buffer = audio;
  src.connect(ctx.destination);
  const at = Math.max(ctx.currentTime + 0.02, playEnd);
  src.start(at);
  playEnd = at + audio.duration;
  pending++;
  sources.add(src);

  // Highlight this sentence when playback starts
  setTimeout(() => {
    answerEl.querySelectorAll("span.now").forEach((s) => (s.className = ""));
    const span = document.getElementById("s" + id);
    if (span) span.className = "now";
  }, Math.max(0, (at - ctx.currentTime) * 1000));

  src.onended = () => {
    sources.delete(src);
    pending--;
    maybeFinished();
  };
}

function stopAudio() {
  sources.forEach((s) => { try { s.stop(); } catch (e) { /* already finished */ } });
  sources.clear();
  pending = 0;
  playEnd = 0;
}

function maybeFinished() {
  if (turnDone && pending === 0 && state === "speaking") {
    answerEl.querySelectorAll("span.now").forEach((s) => (s.className = ""));
    send({ type: "playback_done" });
  }
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function onMessage(ev) {
  if (ev.data instanceof ArrayBuffer) {
    if (ACTIVE.has(state)) playSentence(ev.data);
    return;
  }
  const msg = JSON.parse(ev.data);
  switch (msg.type) {
    case "state":
      if (msg.state === "thinking") {
        if (state === "listening") playCue();
        heardEl.textContent = "";
        answerEl.textContent = "";
        turnDone = false;
      }
      setState(msg.state === "idle" ? "ended" : msg.state);
      break;
    case "heard":
      heardEl.textContent = msg.text;
      heardLang = msg.lang;
      break;
    case "sentence":
      if (ACTIVE.has(state)) addSentence(msg.id, msg.text);
      break;
    case "done":
      if (msg.source) {
        const src = document.createElement("small");
        src.className = "source";
        src.textContent = T().source(msg.source);
        answerEl.appendChild(src);
      }
      turnDone = true;
      maybeFinished();
      break;
    case "session_ended":
      stopAudio();
      heardEl.textContent = "";
      answerEl.textContent = "";
      setState("ended");
      break;
  }
}

function connect() {
  setState("connecting");
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  ws.onmessage = onMessage;
  ws.onclose = () => {
    stopAudio();
    if (state !== "off") setTimeout(connect, 2000);
    setState("connecting");
  };
}

// Microphone and audio output. iOS suspends the AudioContext and ends the microphone track when the iPad
// locks or the page goes to the background; before this, a later "start" left the pet deaf until the page
// was reopened. ensureAudio() checks both and rebuilds what is gone, on every start and when the page returns.
let stream = null;
let micSource = null;
let micNode = null;
let workletReady = false;

function micAlive() {
  return !!stream && stream.getAudioTracks().some((t) => t.readyState === "live" && t.enabled);
}

async function openMic() {
  if (micSource) { try { micSource.disconnect(); } catch (e) { /* already gone */ } }
  if (stream) stream.getTracks().forEach((t) => t.stop());
  stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
  if (!workletReady) {
    await ctx.audioWorklet.addModule("/static/mic-worklet.js");
    micNode = new AudioWorkletNode(ctx, "mic-processor");
    // Send only while listening; not while the pet thinks or speaks (it would hear its own voice), not when stopped
    micNode.port.onmessage = (e) => {
      if (state === "listening" && ws && ws.readyState === WebSocket.OPEN) ws.send(e.data);
    };
    // The node must be connected to the output to run; attach a muted gain so the microphone sound is not played back
    const mute = ctx.createGain();
    mute.gain.value = 0;
    micNode.connect(mute).connect(ctx.destination);
    workletReady = true;
  }
  micSource = ctx.createMediaStreamSource(stream);
  micSource.connect(micNode);
}

async function ensureAudio() {
  if (!ctx || ctx.state === "closed") {
    ctx = new AudioContext({ latencyHint: "interactive" });
    workletReady = false;
    micSource = null;
    loadCue();
  }
  if (ctx.state !== "running") {
    try { await ctx.resume(); } catch (e) { /* resumed on the next tap */ }
  }
  if (!micAlive()) await openMic();
  return ctx.state === "running" && micAlive();
}

async function setup() {
  try {
    await ensureAudio();
  } catch (e) {
    // Without a microphone we can still connect (typed debugging); otherwise prompt for permission
    statusEl.textContent = T().micDenied;
    if (new URLSearchParams(location.search).has("text")) { started = true; connect(); }
    micBtn.disabled = false;
    return;
  }
  started = true;
  connect();
}

micBtn.addEventListener("click", async () => {
  if (!started) {
    micBtn.disabled = true;
    setup();
  } else if (ACTIVE.has(state)) {
    send({ type: "end_session" });
  } else if (state === "ended") {
    heardEl.textContent = "";
    answerEl.textContent = "";
    try {
      await ensureAudio();
    } catch (e) {
      statusEl.textContent = T().micDenied;
      return;
    }
    send({ type: "start" });
  }
});

// Coming back from the lock screen or another app: the iPad may have stopped the microphone; reopen it
// (no permission prompt for an already allowed site) so the next tap just works
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && started) ensureAudio().catch(() => {});
});

// Debugging: add ?text=1 to the URL to show the typing box, so it can be tested without a microphone (the Mac mini has none)
if (new URLSearchParams(location.search).has("text")) {
  const form = document.createElement("form");
  form.className = "debug";
  form.innerHTML = '<input id="q" autocomplete="off"><button id="send"></button>';
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = document.getElementById("q");
    if (q.value.trim() && state === "listening") {
      playCue();
      send({ type: "text", text: q.value.trim() });
    }
    q.value = "";
  });
  document.querySelector(".controls").after(form);
}

// UI language switch
const langBtn = document.getElementById("lang");
function applyLang() {
  const t = T();
  document.documentElement.lang = uiLang;
  langBtn.textContent = t.toggle;
  langBtn.setAttribute("aria-label", t.toggleLabel);
  statusEl.textContent = t.status[state] ?? "";
  micLabel.textContent = ACTIVE.has(state) ? t.stop : t.start;
  const q = document.getElementById("q");
  if (q) {
    q.placeholder = t.ask;
    document.getElementById("send").textContent = t.send;
  }
}
langBtn.addEventListener("click", () => {
  uiLang = uiLang === "zh" ? "en" : "zh";
  try { localStorage.setItem("uiLang", uiLang); } catch (e) { /* if it cannot be saved, it only applies to this visit */ }
  applyLang();
  loadCue();  // the cue follows the page language ("嘿!" / "Hey!")
});
applyLang();

// Private skin: artwork from the Mac's data directory (never in the repo). When /skin.json lists
// images, the SVG cat is replaced by the picture for the current state, plus a round badge that
// plays the role of the collar light: the "this is a program" marker, colored by state.
let skin = null;
let skinImg = null;
function updateSkin(s) {
  if (!skin || !skinImg) return;
  skinImg.src = skin.images[s] || skin.images.idle;
}
fetch("/skin.json", { cache: "no-cache" })
  .then((r) => (r.ok ? r.json() : { default: true }))
  .then((m) => {
    cueUrl = m.cue || null;
    if (ctx) loadCue();
    if (m.default || !m.images || !m.images.idle) return;
    skin = m;
    const wrap = document.createElement("div");
    wrap.className = "skin-wrap";
    skinImg = document.createElement("img");
    skinImg.className = "skin-img";
    skinImg.alt = (m.name && m.name[uiLang]) || "";
    skinImg.draggable = false;
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.setAttribute("aria-hidden", "true");
    wrap.append(skinImg, badge);
    const pet = document.querySelector(".pet");
    pet.style.display = "none";
    pet.before(wrap);
    Object.values(m.images).forEach((src) => { new Image().src = src; });  // preload all states
    updateSkin(state);
  })
  .catch(() => {});

// Skin picker: a round button with the current buddy; tap it, pick another, and the page reloads as that buddy.
// Switching ends a running exploration (the server stops it), like pressing stop.
const skinBtn = document.getElementById("skin");
const sheet = document.getElementById("skin-sheet");
let skinList = null;

function renderSheet() {
  sheet.querySelector(".sheet-title").textContent = T().chooseSkin;
  const grid = sheet.querySelector(".skin-grid");
  grid.textContent = "";
  for (const s of skinList.skins) {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "skin-tile" + (s.id === skinList.active ? " active" : "");
    const img = document.createElement("img");
    img.src = s.thumb;
    img.alt = "";
    img.draggable = false;
    const name = document.createElement("span");
    name.textContent = s.name[uiLang] || s.name.zh;
    tile.append(img, name);
    tile.addEventListener("click", () => chooseSkin(s.id));
    grid.append(tile);
  }
}

async function chooseSkin(id) {
  if (id === skinList.active) { sheet.hidden = true; return; }
  try {
    const r = await fetch("/skin", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }),
    });
    if (r.ok) { state = "off"; location.reload(); }
  } catch (e) { /* offline: keep the current buddy */ }
}

skinBtn.addEventListener("click", () => { renderSheet(); sheet.hidden = false; });
sheet.addEventListener("click", (e) => { if (e.target === sheet) sheet.hidden = true; });

fetch("/skins.json", { cache: "no-cache" })
  .then((r) => (r.ok ? r.json() : null))
  .then((m) => {
    if (!m || !Array.isArray(m.skins) || m.skins.length < 2) return;
    skinList = m;
    const cur = m.skins.find((s) => s.id === m.active) || m.skins[0];
    skinBtn.querySelector("img").src = cur.thumb;
    skinBtn.setAttribute("aria-label", T().chooseSkin);
    skinBtn.hidden = false;
  })
  .catch(() => {});
