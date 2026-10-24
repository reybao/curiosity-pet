// 好奇心伙伴 iPad 页面:麦克风 -> WebSocket -> 服务端;服务端逐句回传文字和音频,这里播放并高亮。
// 不加载任何外部资源。协议见 server.py。
"use strict";

const TTS_RATE = 24000;

// 界面文字(中 / EN)。只管按钮和提示;宠物回答的语言仍跟随孩子提问的语言
const STRINGS = {
  zh: {
    status: { off: "点一下开始", connecting: "正在连接...", listening: "我在听,说吧", thinking: "让我想一想", speaking: "", ended: "下次见!" },
    start: "开始", ptt: "按住说话", end: "结束", ask: "打字提问", send: "发送",
    micDenied: "需要麦克风权限:请让大人在设置里打开",
    source: (t) => `资料来源:维基百科《${t}》`,
    toggle: "EN", toggleLabel: "Switch to English",
  },
  en: {
    status: { off: "Tap to start", connecting: "Connecting...", listening: "I'm listening!", thinking: "Let me think", speaking: "", ended: "See you next time!" },
    start: "Start", ptt: "Hold to talk", end: "Done", ask: "Type a question", send: "Send",
    micDenied: "Microphone access is needed: ask a grown-up to turn it on in Settings",
    source: (t) => `Source: Wikipedia, "${t}"`,
    toggle: "中", toggleLabel: "切换到中文",
  },
};

function savedLang() {
  try {
    const v = localStorage.getItem("uiLang");
    if (v === "zh" || v === "en") return v;
  } catch (e) { /* 隐私模式等情况下存储不可用,用默认值 */ }
  return (navigator.language || "zh").toLowerCase().startsWith("zh") ? "zh" : "en";
}
let uiLang = savedLang();
const T = () => STRINGS[uiLang];

const app = document.getElementById("app");
const statusEl = document.getElementById("status");
const heardEl = document.getElementById("heard");
const answerEl = document.getElementById("answer");
const startBtn = document.getElementById("start");
const pttBtn = document.getElementById("ptt");
const endBtn = document.getElementById("end");

let ctx = null;          // AudioContext,必须在点击里创建(iOS 限制)
let ws = null;
let state = "off";
let holding = false;     // 按住说话中
let playEnd = 0;         // 已排队音频的结束时刻
let pending = 0;         // 还没播完的句子数
let turnDone = false;    // 服务端这一轮已发完
const sources = new Set(); // 正在播或排队的音频,结束时可以停掉
let heardLang = "zh";

function setState(s) {
  state = s;
  app.dataset.state = s;
  statusEl.textContent = T().status[s] ?? "";
  pttBtn.disabled = !(s === "listening");
  endBtn.disabled = s === "off" || s === "connecting";
}

// VAD 判定说完后立即在本地播放提示音,不等服务端。
// 声音是本机合成的短促"喵呜":锯齿波经带通滤波,音高先升后降,约 0.35 秒,不用任何录音素材
function playCue() {
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
  // 英文句子之间要有空格,中文不用
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

  // 开始播放时高亮这一句
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
    playSentence(ev.data);
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
      setState(msg.state);
      break;
    case "heard":
      heardEl.textContent = msg.text;
      heardLang = msg.lang;
      break;
    case "sentence":
      addSentence(msg.id, msg.text);
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
      sources.forEach((s) => s.stop());
      sources.clear();
      pending = 0;
      playEnd = 0;
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
    if (state !== "off") setTimeout(connect, 2000);
    setState("connecting");
  };
}

async function start() {
  ctx = new AudioContext({ latencyHint: "interactive" });
  await ctx.resume();
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
  } catch (e) {
    // 没有麦克风时仍可连接(打字调试),否则提示打开权限
    statusEl.textContent = T().micDenied;
    if (new URLSearchParams(location.search).has("text")) connect();
    return;
  }
  await ctx.audioWorklet.addModule("/static/mic-worklet.js");
  const mic = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, "mic-processor");
  // 只在"在听"或按住说话时发送;宠物说话时不发,避免录到自己的声音
  node.port.onmessage = (e) => {
    if ((state === "listening" || holding) && ws && ws.readyState === WebSocket.OPEN) ws.send(e.data);
  };
  mic.connect(node);
  // 节点需要连到输出才会运行;接一个静音增益,不会把麦克风声音放出来
  const mute = ctx.createGain();
  mute.gain.value = 0;
  node.connect(mute).connect(ctx.destination);
  connect();
}

startBtn.addEventListener("click", () => {
  startBtn.disabled = true;
  start();
});

pttBtn.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  if (state !== "listening") return;
  holding = true;
  pttBtn.classList.add("holding");
  send({ type: "ptt_start" });
});
const release = () => {
  if (!holding) return;
  holding = false;
  pttBtn.classList.remove("holding");
  send({ type: "ptt_end" });
};
pttBtn.addEventListener("pointerup", release);
pttBtn.addEventListener("pointercancel", release);
pttBtn.addEventListener("pointerleave", release);

endBtn.addEventListener("click", () => send({ type: "end_session" }));

// 调试:地址加 ?text=1 显示打字框,不用麦克风也能测(Mac mini 没有麦克风)
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

// 界面语言切换
const langBtn = document.getElementById("lang");
function applyLang() {
  const t = T();
  document.documentElement.lang = uiLang;
  document.querySelector(".start-label").textContent = t.start;
  pttBtn.textContent = t.ptt;
  endBtn.textContent = t.end;
  langBtn.textContent = t.toggle;
  langBtn.setAttribute("aria-label", t.toggleLabel);
  statusEl.textContent = t.status[state] ?? "";
  const q = document.getElementById("q");
  if (q) {
    q.placeholder = t.ask;
    document.getElementById("send").textContent = t.send;
  }
}
langBtn.addEventListener("click", () => {
  uiLang = uiLang === "zh" ? "en" : "zh";
  try { localStorage.setItem("uiLang", uiLang); } catch (e) { /* 存不了就只在本次有效 */ }
  applyLang();
});
applyLang();

// "下次见"之后,点宠物重新开始在听
document.querySelector(".pet").addEventListener("click", () => {
  if (state === "ended") setState("listening");
});
