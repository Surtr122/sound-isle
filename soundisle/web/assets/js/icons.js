const PATHS = {
  music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  layers: '<path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
  tag: '<path d="M20.59 13.41 12 22 2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82Z"/><circle cx="7" cy="7" r="1.5"/>',
  heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0 0-7.8Z"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
  'folder-open': '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1"/><path d="M3 11h18l-2 8H5Z"/>',
  refresh: '<path d="M20 11a8.1 8.1 0 0 0-14.5-4.5L3 9"/><path d="M3 4v5h5"/><path d="M4 13a8.1 8.1 0 0 0 14.5 4.5L21 15"/><path d="M21 20v-5h-5"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  play: '<path d="m7 4 13 8-13 8Z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M8 4h3v16H8zM13 4h3v16h-3z" fill="currentColor" stroke="none"/>',
  prev: '<path d="M19 5 9 12l10 7Z" fill="currentColor" stroke="none"/><path d="M5 5v14"/>',
  next: '<path d="M5 5l10 7L5 19Z" fill="currentColor" stroke="none"/><path d="M19 5v14"/>',
  volume: '<path d="M11 5 6 9H2v6h4l5 4Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  shuffle: '<path d="M16 3h5v5"/><path d="M4 20 21 3"/><path d="M21 16v5h-5"/><path d="M15 15l6 6"/><path d="m4 4 5 5"/>',
  'arrow-right': '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
  'arrow-left': '<path d="M19 12H5"/><path d="m11 18-6-6 6-6"/>',
  disc: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/>',
  piano: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v10M12 4v10M17 4v10M3 14h18"/>',
  mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/>',
  book: '<path d="M4 4h7a3 3 0 0 1 3 3v13a3 3 0 0 0-3-3H4Z"/><path d="M20 4h-4a3 3 0 0 0-3 3v13a3 3 0 0 1 3-3h4Z"/>',
  cap: '<path d="m2 9 10-5 10 5-10 5Z"/><path d="M6 11v5c3 2 9 2 12 0v-5"/><path d="M22 9v6"/>',
  wave: '<path d="M2 12h2M6 8v8M10 5v14M14 9v6M18 7v10M22 11v2"/>',
  dots: '<circle cx="5" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1" fill="currentColor" stroke="none"/>',
  sparkle: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z"/><path d="m19 16 .8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8Z"/>',
  shield: '<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6Z"/><path d="m9 12 2 2 4-4"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  alert: '<path d="M12 3 2 21h20Z"/><path d="M12 9v5M12 17h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  'chevron-down': '<path d="m6 9 6 6 6-6"/>',
  musicnote: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  tune: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/><path d="M1 14h6M9 8h6M17 16h6"/>',
  headphones: '<path d="M4 14a8 8 0 0 1 16 0"/><path d="M4 14v3a2 2 0 0 0 2 2h2v-6H6a2 2 0 0 0-2 2Z"/><path d="M20 14v3a2 2 0 0 1-2 2h-2v-6h2a2 2 0 0 1 2 2Z"/>',
  library: '<path d="M4 3h4v18H4zM10 3h4v18h-4z"/><path d="m16 4 4-1 4 17-4 1z"/>',
  bone: '<path d="M8.5 8.5 15.5 15.5"/><path d="M6.8 6.8a2.4 2.4 0 1 0-3.4 3.4 2.4 2.4 0 0 0 3.4 3.4l3.4-3.4"/><path d="M17.2 17.2a2.4 2.4 0 1 0 3.4-3.4 2.4 2.4 0 0 0-3.4-3.4l-3.4 3.4"/>',
  person: '<circle cx="12" cy="7" r="3.2"/><path d="M5 21v-2.2c0-3 3.1-4.8 7-4.8s7 1.8 7 4.8V21"/>',
  sword: '<path d="m14 3 7-1-1 7L9 20l-4 1 1-4Z"/><path d="m6 18-3 3M4 14l6 6"/>',
  scene: '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="m3 16 5-6 4 5 3-4 6 7"/><circle cx="8" cy="8" r="1.5"/>',
  texture: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 10h16M4 15h16M9 4v16M15 4v16"/>',
  project: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="m12 10 4 2.3v4.4L12 19l-4-2.3v-4.4Z"/>',
  cube: '<path d="m12 2 8 4.6v9.8L12 21l-8-4.6V6.6Z"/><path d="m4 6.6 8 4.6 8-4.6M12 11.2V21"/>',
  file: '<path d="M6 2h8l4 4v16H6Z"/><path d="M14 2v5h5"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="1.8"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  external: '<path d="M14 3h7v7M21 3l-9 9"/><path d="M20 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="m7 22-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
  'repeat-one': '<path d="m17 2 4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="m7 22-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/><path d="M11 10h1v4"/>',
};

export function icon(name, size = 18, className = "") {
  const body = PATHS[name] || PATHS.disc;
  return `<svg class="${className}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;
}

export const CATEGORY_ICON = {
  song: "music",
  instrumental: "piano",
  podcast: "mic",
  audiobook: "book",
  course: "cap",
  sfx: "wave",
  other: "dots",
  animation: "bone",
  character: "person",
  prop: "sword",
  scene: "scene",
  texture: "texture",
  project: "project",
  model: "cube",
  asset_other: "dots",
};

export function categoryIcon(key, size = 18) {
  return icon(CATEGORY_ICON[key] || "disc", size);
}

export function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((node) => {
    if (node.querySelector("svg")) return;
    const size = Number(node.dataset.iconSize) || 18;
    node.innerHTML = icon(node.dataset.icon, size);
  });
}
