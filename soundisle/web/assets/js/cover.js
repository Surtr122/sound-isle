import { escapeHtml, firstCharacter } from "./utils.js";

const SIZE_CLASS = {
  sm: "",
  md: "size-lg",
  lg: "size-lg",
  xl: "size-xl",
  player: "size-player",
};

export function coverMarkup(track, { size = "sm", playing = false, empty = false } = {}) {
  const sizeClass = SIZE_CLASS[size] || "";
  const accent = track?.category?.accent || "#4D7C67";
  const classes = ["cover", sizeClass, empty || !track ? "is-empty" : ""].filter(Boolean).join(" ");
  const initial = escapeHtml(firstCharacter(track?.title || "声"));

  if (empty || !track) {
    return `<div class="${classes}" style="--cover-accent:${escapeHtml(accent)}">
      <span class="vinyl"><span class="vinyl-label">${initial}</span></span>
    </div>`;
  }

  const image = track.has_cover && track.cover_url
    ? `<img src="${escapeHtml(track.cover_url)}" alt="" loading="lazy" decoding="async">`
    : "";
  const overlay = playing
    ? `<span class="playing-overlay"><span class="playing-bars"><span></span><span></span><span></span></span></span>`
    : "";

  return `<div class="${classes}" style="--cover-accent:${escapeHtml(accent)}">
    <span class="vinyl"><span class="vinyl-label">${initial}</span></span>
    ${image}
    ${overlay}
  </div>`;
}
