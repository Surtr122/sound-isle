import { categoryIcon } from "./icons.js";
import { escapeHtml, firstCharacter } from "./utils.js";

function wireframe(track) {
  const key = track.category?.key || "other";
  if (key === "texture") {
    return `<svg class="plate-art" viewBox="0 0 200 160" aria-hidden="true">
      <rect x="44" y="30" width="112" height="100" rx="3"/>
      <path d="M44 96 78 62l28 26 20-20 30 30M44 130h112"/>
      <circle cx="72" cy="58" r="7"/>
    </svg>`;
  }
  if (key === "animation") {
    return `<svg class="plate-art" viewBox="0 0 200 160" aria-hidden="true">
      <path d="M100 28v42M100 70 64 96M100 70l36 26M100 70l-8 58"/>
      <circle cx="100" cy="24" r="7"/><circle cx="62" cy="100" r="6"/>
      <circle cx="138" cy="100" r="6"/><circle cx="90" cy="132" r="6"/>
      <path d="M100 70 64 42M100 70l38-30" class="dim"/>
    </svg>`;
  }
  if (key === "project") {
    return `<svg class="plate-art" viewBox="0 0 200 160" aria-hidden="true">
      <path d="M34 52h50l12 12h70v66H34V52Z"/>
      <path d="M34 52V36h50l12 16M58 102h84M58 118h58"/>
    </svg>`;
  }
  return `<svg class="plate-art" viewBox="0 0 200 160" aria-hidden="true">
    <path d="m100 24 66 38v74l-66 38-66-38V62l66-38Z"/>
    <path d="m34 62 66 38 66-38M100 100v74" class="dim"/>
    <path d="M68 46 134 84v38" class="dim"/>
    <circle cx="34" cy="62" r="3"/><circle cx="166" cy="62" r="3"/><circle cx="100" cy="24" r="3"/>
  </svg>`;
}

export function plateMarkup(track, { size = "sm", detail = false } = {}) {
  const accent = track.category?.accent || "#6F7D86";
  const format = track.format || "ASSET";
  const image = track.thumb_url
    ? `<img class="plate-image" src="${escapeHtml(track.thumb_url)}" alt="" loading="lazy">`
    : "";
  const label = detail ? "ASSET / PLATE" : escapeHtml(format);
  return `
    <div class="asset-plate size-${escapeHtml(size)} ${image ? "has-image" : ""}" style="--plate-accent:${escapeHtml(accent)}">
      <span class="plate-corner tl"></span><span class="plate-corner tr"></span>
      <span class="plate-corner bl"></span><span class="plate-corner br"></span>
      <div class="plate-axis"><span>Y</span><span>X</span><span>Z</span></div>
      <div class="plate-fallback">
        ${wireframe(track)}
        <span class="plate-glyph">${categoryIcon(track.category?.key, detail ? 30 : 20)}</span>
        <span class="plate-initial">${escapeHtml(firstCharacter(track.title))}</span>
      </div>
      ${image}
      <span class="plate-format">${escapeHtml(label)}</span>
      ${detail ? `<span class="plate-category">${escapeHtml(track.category?.name || "其他")}</span>` : ""}
    </div>`;
}
