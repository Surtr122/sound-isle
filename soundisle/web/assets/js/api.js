async function request(path, { method = "GET", body, signal } = {}) {
  const options = {
    method,
    signal,
    headers: { Accept: "application/json" },
  };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new Error("无法连接到声形服务，请确认程序仍在运行。");
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const message = data?.error || data?.message || `请求失败（${response.status}）`;
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data ?? {};
}

function post(path, body) {
  return request(path, { method: "POST", body });
}

export const api = {
  state: () => request("/api/state"),
  health: () => request("/api/health"),
  openLibrary: (path) => post("/api/library/open", { path }),
  addLibrary: (path) => post("/api/library/add", { path }),
  removeLibrary: (sourceId) => post("/api/library/remove", { source_id: sourceId }),
  pickFolder: (initial = "") => post("/api/library/pick", { initial }),
  rescan: (sourceId = "") => post("/api/library/rescan", { source_id: sourceId }),
  dismissMissing: (sourceId, paths) => post("/api/missing/dismiss", { source_id: sourceId, paths }),
  exportMetadata: () => post("/api/metadata/export", {}),
  importMetadata: (metadata) => post("/api/metadata/import", { metadata }),

  addTags: (ids, tags) => post("/api/tags/add", { ids, tags }),
  removeTag: (ids, tag) => post("/api/tags/remove", { ids, tag }),
  setTags: (id, tags) => post("/api/tags/set", { id, tags }),

  setFavorite: (ids, favorite) => post("/api/favorites", { ids, favorite }),

  previewRename: (ids, name, start, digits, separator) =>
    post("/api/rename/preview", { ids, name, start, digits, separator }),
  applyRename: (ids, name, start, digits, separator) =>
    post("/api/rename/apply", { ids, name, start, digits, separator }),

  inspect: (id) => request(`/api/inspect/${encodeURIComponent(id)}`),
  motion: (id) => request(`/api/motion/${encodeURIComponent(id)}`),
  reveal: (id = null) => post("/api/reveal", id ? { id } : {}),

  createCategory: (name, accent = "", parent = "") =>
    post("/api/categories/create", { name, accent, parent }),
  setCategory: (ids, category) => post("/api/category/set", { ids, category }),
  setMemberships: (ids, categories) => post("/api/memberships/set", { ids, categories }),
  removeFromCategory: (ids, category) => post("/api/category/remove", { ids, category }),
  setSubcategory: (ids, subcategory) => post("/api/subcategory/set", { ids, subcategory }),
};

export { request };
