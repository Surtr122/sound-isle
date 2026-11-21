import { $, formatDuration, clamp } from "./utils.js";
import { icon } from "./icons.js";
import { coverMarkup } from "./cover.js";

const ERROR_COPY = {
  1: "播放被中止了，请再试一次。",
  2: "读取这段声音时出了点问题。",
  3: "声音解码失败，浏览器可能不支持这个格式。",
  4: "浏览器无法播放这段声音。",
};

export class Player {
  constructor({ onTrackChange, onFavorite, onError } = {}) {
    this.audio = $("#audio");
    this.cover = $("#player-cover");
    this.kicker = $("#player-kicker");
    this.titleEl = $("#player-title");
    this.artistEl = $("#player-artist");
    this.playBtn = $("#player-play");
    this.playIcon = $("#play-icon");
    this.prevBtn = $("#player-prev");
    this.nextBtn = $("#player-next");
    this.favBtn = $("#player-fav");
    this.waveBtn = $("#player-wave-open");
    this.loopModeButton = $("#player-loop-mode");
    this.viz = $("#player-visualizer");
    this.seek = $("#player-seek");
    this.currentEl = $("#player-current");
    this.durationEl = $("#player-duration");
    this.volumeInput = $("#player-volume");
    this.speedSelect = $("#player-speed");
    this.loopAButton = $("#player-loop-a");
    this.loopBButton = $("#player-loop-b");
    this.loopClearButton = $("#player-loop-clear");
    this.library = null;
    this.current = null;
    this.queue = [];
    this.index = -1;
    this.loopA = null;
    this.loopB = null;
    this.loopMode = "one";
    this._audioCtx = null;
    this._analyser = null;
    this._sourceNode = null;
    this._vizRaf = 0;
    this.onTrackChange = onTrackChange || (() => {});
    this.onFavorite = onFavorite || (() => {});
    this.onError = onError || (() => {});
    this._lastError = 0;
    this._loadVolume();
    this._loadLoopMode();
    this._bind();
    this._initVisualizer();
    this.render();
  }

  _loadVolume() {
    let value = 0.8;
    try {
      // v0.2.0 introduced a bug where a missing key was parsed as 0.
      // Use a fresh key and ignore that broken legacy value once.
      const fresh = localStorage.getItem("soundisle.volume.v2");
      const legacy = localStorage.getItem("soundisle.volume");
      const raw = fresh !== null ? fresh : legacy;
      const stored = raw === null ? NaN : Number(raw);
      const valid = Number.isFinite(stored) && stored >= 0 && stored <= 1;
      if (valid && (fresh !== null || stored > 0)) value = stored;
    } catch {
      // ignore storage restrictions
    }
    this.volume = value;
    this.audio.volume = value;
    if (this.volumeInput) {
      this.volumeInput.value = String(value);
      this.volumeInput.style.setProperty("--volume-progress", `${value * 100}%`);
    }
  }

  _loadLoopMode() {
    let mode = "one";
    try {
      const stored = localStorage.getItem("soundform.loopMode");
      if (stored === "one" || stored === "list") mode = stored;
    } catch {
      // ignore storage restrictions
    }
    this.loopMode = mode;
    this.audio.loop = mode === "one";
    this._renderLoopMode();
  }

  _setLoopMode(mode, { persist = true } = {}) {
    this.loopMode = mode === "list" ? "list" : "one";
    this.audio.loop = this.loopMode === "one";
    if (persist) {
      try {
        localStorage.setItem("soundform.loopMode", this.loopMode);
      } catch {
        // ignore storage restrictions
      }
    }
    this._renderLoopMode();
  }

  _renderLoopMode() {
    if (!this.loopModeButton) return;
    const one = this.loopMode === "one";
    this.loopModeButton.disabled = !this.current;
    this.loopModeButton.classList.toggle("is-loop-one", one);
    this.loopModeButton.innerHTML = icon(one ? "repeat-one" : "repeat", 14);
    this.loopModeButton.setAttribute("aria-pressed", one ? "true" : "false");
    this.loopModeButton.setAttribute("aria-label", one ? "单曲循环" : "顺序播放");
    this.loopModeButton.title = one ? "单曲循环：开（点击切换顺序播放）" : "顺序播放（点击切换单曲循环）";
  }

  _initVisualizer() {
    if (!this.viz) return;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) {
      this._drawIdleVisualizer();
      return;
    }
    try {
      this._audioCtx = new Ctx();
      this._analyser = this._audioCtx.createAnalyser();
      this._analyser.fftSize = 64;
      this._analyser.smoothingTimeConstant = 0.78;
      this._sourceNode = this._audioCtx.createMediaElementSource(this.audio);
      this._sourceNode.connect(this._analyser);
      this._analyser.connect(this._audioCtx.destination);
    } catch {
      this._audioCtx = null;
      this._analyser = null;
      this._sourceNode = null;
    }
    this._drawIdleVisualizer();
  }

  _ensureVisualizer() {
    if (!this.viz) return;
    if (this._audioCtx?.state === "suspended") {
      this._audioCtx.resume().catch(() => {});
    }
    if (!this._analyser) return;
    if (!this._vizRaf) this._drawVisualizer();
  }

  _stopVisualizer() {
    if (this._vizRaf) {
      cancelAnimationFrame(this._vizRaf);
      this._vizRaf = 0;
    }
    this._drawIdleVisualizer();
  }

  _drawIdleVisualizer() {
    const canvas = this.viz;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "rgba(244, 238, 223, 0.12)";
    ctx.fillRect(0, canvas.height / 2 - 1, canvas.width, 2);
  }

  _drawVisualizer() {
    const canvas = this.viz;
    const analyser = this._analyser;
    if (!canvas || !analyser) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const data = new Uint8Array(analyser.frequencyBinCount);
    const bars = 24;
    const gap = 2;
    const barWidth = Math.max(1, (canvas.width - gap * (bars - 1)) / bars);
    const step = () => {
      if (!this._analyser) return;
      if (this.audio.paused) {
        this._drawIdleVisualizer();
        this._vizRaf = 0;
        return;
      }
      analyser.getByteFrequencyData(data);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (let index = 0; index < bars; index += 1) {
        const sourceIndex = Math.min(data.length - 1, Math.floor((index / bars) ** 1.6 * data.length));
        const level = data[sourceIndex] / 255;
        const height = Math.max(2, level * canvas.height);
        const x = index * (barWidth + gap);
        const y = (canvas.height - height) / 2;
        ctx.fillStyle = level > 0.55 ? "#d9b67f" : "rgba(198, 93, 59, 0.72)";
        ctx.fillRect(x, y, barWidth, height);
      }
      this._vizRaf = requestAnimationFrame(step);
    };
    if (this._vizRaf) cancelAnimationFrame(this._vizRaf);
    step();
  }

  _bind() {
    this.playBtn?.addEventListener("click", () => this.toggle());
    this.prevBtn?.addEventListener("click", () => this.previous());
    this.nextBtn?.addEventListener("click", () => this.next(false));
    this.loopModeButton?.addEventListener("click", () => {
      this._setLoopMode(this.loopMode === "one" ? "list" : "one");
    });
    this.favBtn?.addEventListener("click", () => {
      if (!this.current) return;
      this.onFavorite(this.current);
    });

    this.seek?.addEventListener("input", () => {
      const duration = this.audio.duration;
      if (!Number.isFinite(duration) || duration <= 0) return;
      this.audio.currentTime = (Number(this.seek.value) / 100) * duration;
      this._renderProgress();
    });

    this.volumeInput?.addEventListener("input", () => {
      const value = clamp(Number(this.volumeInput.value) || 0, 0, 1);
      this.volume = value;
      this.audio.volume = value;
      this.volumeInput.style.setProperty("--volume-progress", `${value * 100}%`);
      try {
        localStorage.setItem("soundisle.volume.v2", String(value));
      } catch {
        // ignore storage restrictions
      }
    });

    this.speedSelect?.addEventListener("change", () => {
      const rate = clamp(Number(this.speedSelect.value) || 1, 0.25, 4);
      this.audio.playbackRate = rate;
    });

    this.loopAButton?.addEventListener("click", () => {
      if (!this.current) return;
      this.loopA = this.audio.currentTime || 0;
      if (this.loopB !== null && this.loopB <= this.loopA) this.loopB = null;
      this._renderLoop();
    });

    this.loopBButton?.addEventListener("click", () => {
      if (!this.current) return;
      const point = this.audio.currentTime || 0;
      if (this.loopA === null) this.loopA = 0;
      if (point > this.loopA + 0.15) {
        this.loopB = point;
        this._renderLoop();
      }
    });

    this.loopClearButton?.addEventListener("click", () => {
      this.loopA = null;
      this.loopB = null;
      this._renderLoop();
    });

    this.audio.addEventListener("play", () => {
      this._renderState();
      this._setMediaSession();
      this._ensureVisualizer();
    });
    this.audio.addEventListener("pause", () => {
      this._renderState();
      this._stopVisualizer();
    });
    this.audio.addEventListener("timeupdate", () => {
      if (
        this.loopA !== null &&
        this.loopB !== null &&
        this.loopB > this.loopA &&
        this.audio.currentTime >= this.loopB
      ) {
        this.audio.currentTime = this.loopA;
      }
      this._renderProgress();
    });
    this.audio.addEventListener("loadedmetadata", () => this._renderProgress());
    this.audio.addEventListener("durationchange", () => this._renderProgress());
    this.audio.addEventListener("ended", () => {
      if (this.loopMode === "one") {
        this.audio.currentTime = 0;
        this._playSafely();
        return;
      }
      if (!this.queue.length) {
        this._renderState();
        return;
      }
      let index = this.queue.indexOf(this.current?.id);
      if (index < 0) index = this.index;
      if (index >= 0 && index < this.queue.length - 1) {
        this.next(true);
      } else {
        this._renderState();
        this._renderProgress();
      }
    });
    this.audio.addEventListener("error", () => {
      if (!this.audio.currentSrc) return;
      const now = Date.now();
      if (now - this._lastError < 1200) return;
      this._lastError = now;
      const code = this.audio.error?.code;
      this.onError(ERROR_COPY[code] || "这段声音暂时无法播放。");
      this._renderState();
    });

    if ("mediaSession" in navigator) {
      const guard = (name, handler) => {
        try {
          navigator.mediaSession.setActionHandler(name, handler);
        } catch {
          // unsupported action
        }
      };
      guard("play", () => this.resume());
      guard("pause", () => this.pause());
      guard("previoustrack", () => this.previous());
      guard("nexttrack", () => this.next(false));
      guard("seekbackward", () => this._seekBy(-10));
      guard("seekforward", () => this._seekBy(10));
    }
  }

  _seekBy(seconds) {
    if (!this.current) return;
    const duration = this.audio.duration;
    if (!Number.isFinite(duration) || duration <= 0) return;
    this.audio.currentTime = clamp(this.audio.currentTime + seconds, 0, duration);
  }

  setLibrary(library) {
    this.library = library;
    if (!library) return;
    if (this.current) {
      const fresh = library.tracks.find((track) => track.id === this.current.id);
      if (fresh) {
        this.current = fresh;
        this._renderFavorite();
      }
    }
    const validIds = new Set(library.tracks.map((track) => track.id));
    const nextQueue = this.queue.filter((id) => validIds.has(id));
    if (nextQueue.length !== this.queue.length) {
      this.queue = nextQueue;
      this.index = this.current ? this.queue.indexOf(this.current.id) : -1;
      this._renderControls();
    }
  }

  setQueue(tracks) {
    this.queue = Array.isArray(tracks) ? tracks.map((track) => track.id) : [];
    this.index = this.current ? this.queue.indexOf(this.current.id) : -1;
    this._renderControls();
  }

  playTrack(track, queue = null) {
    if (!track) return;
    if (queue) this.setQueue(queue);
    if (this.current?.id === track.id && this.audio.currentSrc) {
      if (this.audio.paused) this.resume();
      else this.pause();
      return;
    }
    this.current = track;
    this.index = this.queue.indexOf(track.id);
    this.loopA = null;
    this.loopB = null;
    this.audio.src = track.stream_url;
    this.render();
    this._playSafely();
  }

  _startById(trackId) {
    const track = this.library?.tracks.find((item) => item.id === trackId);
    if (!track) {
      this.next(false);
      return;
    }
    this.current = track;
    this.index = this.queue.indexOf(track.id);
    this.loopA = null;
    this.loopB = null;
    this.audio.src = track.stream_url;
    this.render();
    this._playSafely();
  }

  replaceTrack(track) {
    if (!track) return;
    const time = this.audio.currentTime || 0;
    const wasPlaying = !this.audio.paused && Boolean(this.audio.currentSrc);
    this.current = track;
    this.audio.src = track.stream_url;
    this.render();
    const restore = () => {
      if (Number.isFinite(time) && time > 0) {
        try {
          this.audio.currentTime = Math.min(time, this.audio.duration || time);
        } catch {
          // ignore seek failure
        }
      }
      if (wasPlaying) this._playSafely();
    };
    if (this.audio.readyState >= 1) restore();
    else this.audio.addEventListener("loadedmetadata", restore, { once: true });
  }

  _playSafely() {
    const promise = this.audio.play();
    if (promise && typeof promise.catch === "function") {
      promise.catch((error) => {
        if (error?.name === "AbortError") return;
        if (error?.name === "NotAllowedError") {
          this.onError("浏览器拦截了自动播放，请再点一次播放键。");
          return;
        }
        this.onError("播放没有开始，请检查声音文件是否仍然存在。");
      });
    }
  }

  toggle() {
    if (!this.current) return;
    if (this.audio.paused) this.resume();
    else this.pause();
  }

  resume() {
    if (!this.current) return;
    if (!this.audio.currentSrc) {
      this.audio.src = this.current.stream_url;
      this.render();
    }
    this._playSafely();
  }

  pause() {
    this.audio.pause();
  }

  stop() {
    this.audio.pause();
    this.audio.removeAttribute("src");
    this.audio.load();
    this._stopVisualizer();
    this.current = null;
    this.queue = [];
    this.index = -1;
    this.render();
    this.onTrackChange(null);
  }

  clear() {
    this.stop();
  }

  previous() {
    if (!this.current) return;
    if (this.audio.currentTime > 3.2) {
      this.audio.currentTime = 0;
      this._renderProgress();
      return;
    }
    if (!this.queue.length) {
      this.audio.currentTime = 0;
      return;
    }
    this.index = this.index <= 0 ? this.queue.length - 1 : this.index - 1;
    this._startById(this.queue[this.index]);
  }

  next(auto = false) {
    if (!this.current || !this.queue.length) return;
    let index = this.queue.indexOf(this.current.id);
    if (index < 0) index = this.index;
    if (index < 0) index = 0;
    const last = index >= this.queue.length - 1;
    if (last && auto) {
      this._renderState();
      this._renderProgress();
      return;
    }
    this.index = last ? 0 : index + 1;
    this._startById(this.queue[this.index]);
  }

  setFavoriteState(trackId, favorite) {
    if (this.current?.id === trackId) {
      this.current = { ...this.current, favorite };
      this._renderFavorite();
    }
  }

  render() {
    if (!this.current) {
      this.cover.innerHTML = coverMarkup(null, { size: "player", empty: true });
      this.kicker.textContent = "NOW PLAYING";
      this.titleEl.textContent = "选一段声音，让岛上有回响";
      this.artistEl.textContent = "声形 · 本地播放器";
      this.playBtn.disabled = true;
      this.prevBtn.disabled = true;
      this.nextBtn.disabled = true;
      this.favBtn.disabled = true;
      if (this.waveBtn) this.waveBtn.disabled = true;
      this.favBtn.classList.remove("is-fav");
      this.seek.disabled = true;
      this.seek.value = "0";
      this.seek.style.setProperty("--seek-progress", "0%");
      this.currentEl.textContent = "0:00";
      this.durationEl.textContent = "0:00";
      this._renderControls();
      this._renderState();
      return;
    }

    this.cover.innerHTML = coverMarkup(this.current, { size: "player" });
    this.titleEl.textContent = this.current.title || this.current.filename || "未命名声音";
    const meta = [this.current.artist, this.current.album].filter(Boolean).join(" · ");
    this.artistEl.textContent = meta || "未知艺术家";
    this.playBtn.disabled = false;
    this.favBtn.disabled = false;
    if (this.waveBtn) this.waveBtn.disabled = false;
    this.seek.disabled = false;
    this._renderFavorite();
    this._renderControls();
    this._renderState();
    this._renderProgress();
    this._setMediaSession();
  }

  _renderState() {
    if (!this.current) {
      this.kicker.textContent = "NOW PLAYING";
      this.playIcon.innerHTML = icon("play", 17);
      this.playBtn.setAttribute("aria-label", "播放");
      return;
    }
    const paused = this.audio.paused;
    this.kicker.textContent = paused ? "PAUSED" : "NOW PLAYING";
    this.playIcon.innerHTML = icon(paused ? "play" : "pause", 17);
    this.playBtn.setAttribute("aria-label", paused ? "播放" : "暂停");
  }

  _renderLoop() {
    const hasCurrent = Boolean(this.current);
    if (this.loopAButton) {
      this.loopAButton.disabled = !hasCurrent;
      this.loopAButton.classList.toggle("is-set", this.loopA !== null);
      this.loopAButton.title = this.loopA !== null ? `A 点 ${formatDuration(this.loopA)}` : "设置 A 点";
    }
    if (this.loopBButton) {
      this.loopBButton.disabled = !hasCurrent;
      this.loopBButton.classList.toggle("is-set", this.loopB !== null);
      this.loopBButton.title = this.loopB !== null ? `B 点 ${formatDuration(this.loopB)}` : "设置 B 点";
    }
    if (this.loopClearButton) this.loopClearButton.disabled = !hasCurrent || (this.loopA === null && this.loopB === null);
  }

  _renderControls() {
    const hasCurrent = Boolean(this.current);
    this.playBtn.disabled = !hasCurrent;
    this.prevBtn.disabled = !hasCurrent || this.queue.length === 0;
    this.nextBtn.disabled = !hasCurrent || this.queue.length < 2;
    this.favBtn.disabled = !hasCurrent;
    this.seek.disabled = !hasCurrent;
    this._renderLoop();
    this._renderLoopMode();
  }

  _renderFavorite() {
    const favorite = Boolean(this.current?.favorite);
    this.favBtn.classList.toggle("is-fav", favorite);
    this.favBtn.setAttribute("aria-pressed", favorite ? "true" : "false");
    this.favBtn.setAttribute("aria-label", favorite ? "取消收藏" : "收藏当前声音");
  }

  _renderProgress() {
    if (!this.current) return;
    const audioDuration = this.audio.duration;
    const duration = Number.isFinite(audioDuration) && audioDuration > 0
      ? audioDuration
      : Number(this.current.duration) || 0;
    const current = Number.isFinite(this.audio.currentTime) ? this.audio.currentTime : 0;
    const percent = duration > 0 ? clamp((current / duration) * 100, 0, 100) : 0;

    this.seek.max = String(duration || 100);
    this.seek.value = String(duration > 0 ? current : 0);
    this.seek.style.setProperty("--seek-progress", `${percent}%`);
    this.currentEl.textContent = formatDuration(current);
    this.durationEl.textContent = formatDuration(duration);
  }

  _setMediaSession() {
    if (!("mediaSession" in navigator) || !this.current) return;
    const artwork = [];
    if (this.current.has_cover && this.current.cover_url) {
      try {
        artwork.push({ src: new URL(this.current.cover_url, window.location.href).href });
      } catch {
        // ignore invalid URL
      }
    }
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: this.current.title || this.current.filename || "未命名声音",
        artist: this.current.artist || "未知艺术家",
        album: this.current.album || "声形",
        artwork,
      });
      if (Number.isFinite(this.audio.duration) && this.audio.duration > 0) {
        navigator.mediaSession.setPositionState?.({
          duration: this.audio.duration,
          playbackRate: this.audio.playbackRate || 1,
          position: clamp(this.audio.currentTime || 0, 0, this.audio.duration),
        });
      }
    } catch {
      // Media Session is best-effort
    }
  }
}
