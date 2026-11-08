const $ = (s) => document.querySelector(s);
const photoCache = new Map();
let token = $('meta[name="papertrail-token"]').content;
const paths = {
  photo: "M3 4h18v16H3z M3 16l5-5 4 4 3-3 6 6 M15 8h.01",
  library: "M4 3h12l3 3v15H4z M8 8h7 M8 12h7 M8 16h4",
  lock: "M7 10V7a5 5 0 0 1 10 0v3 M5 10h14v11H5z M12 14v3",
  shield: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M8 12l3 3 5-6",
  spark: "M12 2l2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5z",
  help: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20 M9 8a3 3 0 0 1 6 0c0 2-3 2-3 5 M12 17h.01",
  plus: "M12 5v14 M5 12h14",
  search: "M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16 M16 16l6 6",
  close: "M6 6l12 12 M6 18L18 6",
  folder: "M3 5h7l2 3h9v12H3z",
  sort: "M7 4v16 M3 16l4 4 4-4 M14 6h7 M14 11h5 M14 16h3",
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  list: "M8 5h13 M8 12h13 M8 19h13 M3 5h.1 M3 12h.1 M3 19h.1",
  trash: "M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7",
  upload: "M12 16V3 M7 8l5-5 5 5 M3 15v6h18v-6",
  check: "M5 12l4 4L19 6",
};
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(svg.namespaceURI, "path");
  path.setAttribute("d", paths[name] || paths.library);
  svg.append(path);
  return svg;
}
document
  .querySelectorAll("[data-icon]")
  .forEach((el) => el.append(icon(el.dataset.icon)));
function text(tag, value, cls) {
  const el = document.createElement(tag);
  el.textContent = value;
  if (cls) el.className = cls;
  return el;
}
async function request(path, body, retried = false) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: {
      "X-Papertrail-Token": token,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (response.status === 403 && !retried) {
    const home = await fetch("/");
    const html = new DOMParser().parseFromString(
      await home.text(),
      "text/html",
    );
    const fresh = html.querySelector('meta[name="papertrail-token"]')?.content;
    if (fresh && fresh !== token) {
      token = fresh;
      return request(path, body, true);
    }
  }
  return response;
}
async function api(path, body) {
  const response = await request(path, body);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Something went wrong");
  return data;
}
let sequence = 0,
  wasRunning = false,
  filter = "all",
  cached = [],
  uploading = false,
  visibleLimit = 60;
let libraryRevision = null,
  sourcePrefix = "",
  pollCount = 0,
  sources = [],
  lastSources = "",
  reader = null,
  readerSequence = 0,
  readerMode = "original",
  undoToken = null,
  toastTimer,
  uploadCancelled = false;
function message(value) {
  $("#notice").hidden = !value;
  $("#notice").textContent = value;
}
function marked(target, value) {
  let active = false;
  for (const part of value.split(/([\x01\x02])/)) {
    if (part === "\x01") active = true;
    else if (part === "\x02") active = false;
    else target.append(text(active ? "mark" : "span", part));
  }
}
function emptyState(query) {
  if (query || filter !== "all") {
    const el = text("div", "", "no-results");
    el.append(
      text("h3", "Nothing here just yet."),
      text("p", "Try another file type, fewer words, or add more documents."),
    );
    const clear = text("button", "Reset search", "primary");
    clear.style.margin = "20px auto";
    clear.onclick = () => {
      $("#query").value = "";
      setFilter("all");
      search();
    };
    el.append(clear);
    return el;
  }
  const empty = text("div", "", "empty"),
    art = text("div", "", "empty-art");
  art.setAttribute("aria-hidden", "true");
  for (const kind of ["back", "middle", "front"]) {
    const page = text("div", "", "empty-page " + kind);
    if (kind === "front") {
      page.append(
        icon("library"),
        text("div", "A little more order.", "mini-heading"),
      );
      for (let i = 0; i < 4; i++)
        page.append(text("div", "", "mini-line" + (i === 3 ? " short" : "")));
      const stamp = text("div", "", "mini-stamp");
      stamp.append(icon("check"));
      page.append(stamp);
    }
    art.append(page);
  }
  const star = text("div", "", "empty-star");
  star.append(icon("spark"));
  art.append(star);
  const copy = text("div", "", "empty-copy");
  copy.append(
    text("div", "YOUR NEXT GOOD HABIT", "eyebrow"),
    text("h3", "A little order for your everyday."),
    text(
      "p",
      "The receipt you’ll need. The contract you forgot. Give them a home you can actually search.",
    ),
  );
  const button = text("button", "Add your first documents", "primary");
  button.prepend(icon("plus"));
  button.onclick = () => $("#file-picker").click();
  copy.append(
    button,
    text("small", "Or drop your files anywhere in this window."),
  );
  empty.append(art, copy);
  return empty;
}
function setFilter(value) {
  filter = value;
  visibleLimit = 60;
  document.querySelectorAll("[data-filter]").forEach((b) => {
    b.classList.toggle("active", b.dataset.filter === value);
    b.setAttribute("aria-pressed", String(b.dataset.filter === value));
  });
  render();
}
function render() {
  const query = $("#query").value.trim();
  $("#clear-search").hidden = !query;
  let rows = cached.filter((r) => {
    const ext = r.name.split(".").pop().toLowerCase();
    if (
      sourcePrefix &&
      !r.path
        .replaceAll("\\", "/")
        .toLowerCase()
        .startsWith(
          sourcePrefix.replaceAll("\\", "/").toLowerCase().replace(/\/$/, "") +
            "/",
        )
    )
      return false;
    return (
      filter === "all" ||
      (filter === "pdf" && ext === "pdf") ||
      (filter === "image" && r.kind === "image") ||
      (filter === "text" && ["txt", "md"].includes(ext))
    );
  });
  if ($("#sort").value === "name")
    rows = [...rows].sort((a, b) => a.name.localeCompare(b.name));
  if ($("#sort").value === "recent")
    rows = [...rows].sort((a, b) => b.modified_ns - a.modified_ns);
  $("#result-title").textContent = query
    ? "Search results"
    : sourcePrefix
      ? sources.find((s) => s.path === sourcePrefix)?.name || "Connected folder"
      : "Your documents";
  $("#result-count").textContent = rows.length
    ? rows.length + " " + (rows.length === 1 ? "file" : "files")
    : "";
  $("#results").replaceChildren();
  $("#load-more").hidden = rows.length <= visibleLimit;
  if (!rows.length) {
    $("#results").append(emptyState(query));
    return;
  }
  for (const result of rows.slice(0, visibleLimit)) {
    const card = text("article", "", "card"),
      cover = text("div", "", "document-cover"),
      sheet = text("div", "", "cover-sheet");
    sheet.append(
      text("div", "PAPERTRAIL / TEXT PREVIEW", "cover-label"),
      text("h4", result.name.replace(/\.[^.]+$/, "")),
    );
    const excerpt = text("p", "");
    marked(excerpt, result.snippet);
    sheet.append(excerpt);
    cover.append(sheet);
    if (result.is_image || result.kind === "pdf") {
      cover.replaceChildren();
      cover.classList.add(result.is_image ? "photo-cover" : "pdf-cover");
      const img = document.createElement("img");
      img.alt = result.name;
      img.loading = "lazy";
      cover.append(img);
      loadPreview(img, result, result.page, 500);
    }
    const content = text("div", "", "card-body"),
      title = text("div", "", "card-title"),
      titles = text("div", "");
    titles.append(
      text("h3", result.name),
      text(
        "div",
        result.is_image
          ? "Photo · Stored locally"
          : result.page_count > 1
            ? result.page_count +
              " pages · " +
              (query ? "match on page " + result.page : "PDF document")
            : "Stored locally",
        "file-meta",
      ),
    );
    title.append(
      text("div", result.name.split(".").pop().toUpperCase(), "file-type"),
      titles,
    );
    content.append(title);
    if (!result.available || result.error)
      content.append(
        text(
          "div",
          result.error ? "Needs re-indexing" : "Original unavailable",
          "file-warning",
        ),
      );
    if (query && result.match_type.includes("visual"))
      content.append(
        text(
          "div",
          result.match_type === "visual"
            ? "Visual match"
            : "Text + visual match",
          "visual-match",
        ),
      );
    if (query && result.snippet) {
      const snippet = text("p", "", "match-snippet");
      marked(snippet, result.snippet);
      content.append(snippet);
    }
    const actions = text("div", "", "actions"),
      read = text(
        "button",
        result.is_image ? "View photo →" : "Read document →",
        "read-button",
      ),
      open = text("button", "Open original ↗", "open-button"),
      remove = text("button", "", "remove");
    remove.append(icon("trash"));
    remove.setAttribute("aria-label", "Remove from library");
    remove.title = "Remove from library";
    read.onclick = () => openReader(result, result.page);
    open.onclick = async () => {
      try {
        await api("/api/open", { id: result.id });
      } catch (e) {
        message(e.message);
      }
    };
    remove.onclick = async () => {
      try {
        const removed = await api("/api/remove", { id: result.id });
        discardPhoto(result.id);
        await search();
        await poll();
        toast("Removed from library. Original kept.", removed.undo_token);
      } catch (e) {
        message(e.message);
      }
    };
    actions.append(read, open, remove);
    card.append(cover, content, actions);
    $("#results").append(card);
  }
}
async function search() {
  const id = ++sequence;
  $("#results").setAttribute("aria-busy", "true");
  try {
    const rows = await api(
      "/api/search?q=" +
        encodeURIComponent($("#query").value.trim()) +
        "&mode=" +
        $("#search-mode").value,
    );
    if (id !== sequence) return;
    cached = rows;
    visibleLimit = 60;
    message("");
    render();
  } catch (e) {
    message(e.message);
  } finally {
    if (id === sequence) $("#results").setAttribute("aria-busy", "false");
  }
}
$("#search-form").onsubmit = (e) => {
  e.preventDefault();
  search();
};
$("#clear-search").onclick = () => {
  $("#query").value = "";
  search();
  $("#query").focus();
};
document
  .querySelectorAll("[data-filter]")
  .forEach((b) => (b.onclick = () => setFilter(b.dataset.filter)));
$("#sort").onchange = render;
for (const view of ["grid", "list"])
  $("#" + view + "-view").onclick = () => {
    $("#results").classList.toggle("list-mode", view === "list");
    for (const other of ["grid", "list"]) {
      const button = $("#" + other + "-view");
      button.classList.toggle("active", other === view);
      button.setAttribute("aria-pressed", String(other === view));
    }
  };
$("#library-nav").onclick = () => {
  $("#query").value = "";
  filter = "all";
  sourcePrefix = "";
  setFilter("all");
  search();
};
$("#add").onclick = () => showImport("all");
$("#import-form").onsubmit = async (e) => {
  e.preventDefault();
  $("#import-error").textContent = "";
  $("#start-import").disabled = true;
  try {
    await api("/api/import", {
      path: $("#folder").value,
      scope: $("#import-scope").value,
      watch: $("#watch-folder").checked,
    });
    wasRunning = true;
    $("#import-dialog").close();
    await poll();
    await loadSources();
    toast("Import started. Your originals stay in place.");
  } catch (error) {
    $("#import-error").textContent = error.message;
  } finally {
    $("#start-import").disabled = false;
  }
};
async function poll() {
  try {
    const status = await api("/api/status");
    $("#count").textContent = status.count;
    $("#add").disabled = status.running || uploading;
    $("#photo-library").disabled = status.running || uploading;
    $("#cancel-import").hidden = !(status.running || uploading);
    $("#connection").textContent = "Local workspace";
    $("#status").textContent = status.running
      ? `${status.stage || "Reading your files…"} · ${status.done} / ${status.total}`
      : "";
    $("#import-progress").hidden = !status.running;
    $("#import-progress").max = Math.max(status.total, 1);
    $("#import-progress").value = status.done;
    const issues = [...status.errors, ...(status.warnings || [])];
    $("#issues").hidden = !issues.length;
    $("#error-list").replaceChildren(
      ...issues.map((e) => text("p", e.file + ": " + e.error)),
    );
    const state = status.vision.state;
    $("#vision-banner").hidden = !(
      status.photo_count || ["downloading", "loading", "error"].includes(state)
    );
    $("#vision-title").textContent =
      state === "ready"
        ? "Search photos by what’s in them"
        : state === "error"
          ? "Photos saved. Visual indexing needs attention."
          : state === "idle"
            ? "Visual search on this device"
            : "Setting up visual search";
    $("#vision-description").textContent = status.pending_photos
      ? `${status.pending_photos} photo(s) waiting for visual indexing. ${status.vision.message}`
      : status.vision.message +
        (state === "ready"
          ? " Matches are visual suggestions, not verified labels."
          : "");
    $("#retry-vision").hidden = !status.pending_photos || status.running;
    if (
      (wasRunning && !status.running) ||
      (libraryRevision !== null && libraryRevision !== status.revision)
    ) {
      await search();
      await loadSources();
    }
    libraryRevision = status.revision;
    wasRunning = status.running;
    if (++pollCount % 5 === 0) await loadSources();
  } catch (e) {
    $("#connection").textContent = "Disconnected";
    message("Cannot reach Papertrail. Reopen the launcher to reconnect.");
  }
}
$("#close-preview").onclick = () => {
  $("#preview").close();
  readerSequence++;
};
$("#help").onclick = () => $("#help-dialog").showModal();
$("#close-help").onclick = () => $("#help-dialog").close();
$("#upload").onclick = () => $("#file-picker").click();
async function uploadFiles(files) {
  if (uploading) return;
  uploading = true;
  uploadCancelled = false;
  $("#upload").disabled = true;
  message("");
  const failures = [];
  try {
    for (const file of files) {
      if (uploadCancelled) break;
      try {
        if (file.size > 25 * 1024 * 1024)
          throw new Error("Exceeds 25 MB. Use folder import instead.");
        $("#status").textContent = "Reading " + file.name + "…";
        const data = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result.split(",")[1]);
          reader.onerror = () => reject(new Error("Could not read file"));
          reader.readAsDataURL(file);
        });
        const imported = await api("/api/upload", { name: file.name, data });
        if (imported.duplicate) {
          toast(file.name + " is already in your library.");
          continue;
        }
        wasRunning = true;
        let result;
        while ((result = await api("/api/status")).running)
          await new Promise((r) => setTimeout(r, 500));
        failures.push(...result.errors.map((e) => e.file + ": " + e.error));
        await search();
        await poll();
      } catch (e) {
        failures.push(file.name + ": " + e.message);
      }
    }
  } finally {
    uploading = false;
    $("#upload").disabled = false;
    $("#file-picker").value = "";
    if (failures.length) message(failures.join(" · "));
  }
}
$("#file-picker").onchange = (e) => uploadFiles(e.target.files);
let dragDepth = 0;
document.addEventListener("dragenter", (e) => {
  if (e.dataTransfer.types.includes("Files")) {
    e.preventDefault();
    dragDepth++;
    document.body.classList.add("dragging");
  }
});
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("dragleave", () => {
  dragDepth--;
  if (dragDepth <= 0) document.body.classList.remove("dragging");
});
document.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("dragging");
  uploadFiles(e.dataTransfer.files);
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "k") {
    e.preventDefault();
    $("#query").focus();
  }
});
let debounce;
$("#query").addEventListener("input", () => {
  clearTimeout(debounce);
  debounce = setTimeout(search, 400);
});
search();
poll();
loadSources();
setInterval(poll, 1500);

async function photoURL(id, version) {
  const key = id + ":" + version;
  if (!photoCache.has(key)) {
    for (const old of [...photoCache.keys()])
      if (old.startsWith(id + ":")) {
        photoCache
          .get(old)
          .then((url) => URL.revokeObjectURL(url))
          .catch(() => {});
        photoCache.delete(old);
      }
    photoCache.set(
      key,
      fetch("/api/image?id=" + id, { headers: { "X-Papertrail-Token": token } })
        .then(async (response) => {
          if (!response.ok) throw new Error("Photo preview unavailable");
          return URL.createObjectURL(await response.blob());
        })
        .catch((error) => {
          photoCache.delete(key);
          throw error;
        }),
    );
  }
  return photoCache.get(key);
}
async function loadPhoto(img, id, version) {
  img.dataset.fileId = id;
  try {
    const url = await photoURL(id, version);
    if (img.dataset.fileId === String(id)) img.src = url;
  } catch (e) {
    img.alt = "Photo preview unavailable";
  }
}
function discardPhoto(id) {
  for (const key of [...photoCache.keys()])
    if (key.startsWith(id + ":")) {
      const promise = photoCache.get(key);
      photoCache.delete(key);
      promise.then((url) => URL.revokeObjectURL(url)).catch(() => {});
    }
}
$("#search-mode").onchange = search;
$("#load-more").onclick = () => {
  visibleLimit += 60;
  render();
};
$("#retry-vision").onclick = async () => {
  try {
    await api("/api/reindex-photos", {});
    wasRunning = true;
    await poll();
  } catch (e) {
    message(e.message);
  }
};

function toast(value, token = null) {
  clearTimeout(toastTimer);
  undoToken = token;
  $("#toast-message").textContent = value;
  $("#undo-remove").hidden = !token;
  $("#toast").hidden = false;
  toastTimer = setTimeout(
    () => {
      $("#toast").hidden = true;
      undoToken = null;
    },
    token ? 120000 : 6500,
  );
}
$("#close-toast").onclick = () => {
  $("#toast").hidden = true;
};
$("#undo-remove").onclick = async () => {
  if (!undoToken) return;
  try {
    await api("/api/restore", { undo_token: undoToken });
    await search();
    await poll();
    toast("Restored to your library.");
  } catch (error) {
    message(error.message);
  }
};
$("#cancel-import").onclick = async () => {
  uploadCancelled = true;
  try {
    await api("/api/cancel", {});
    toast("Stopping after the current file. Folder sync has been paused.");
  } catch (error) {
    message(error.message);
  }
};

async function showImport(scope = "photos") {
  $("#sources-dialog").close();
  $("#import-scope").value = scope;
  $("#watch-folder").checked = true;
  $("#import-error").textContent = "";
  $("#import-title").textContent =
    scope === "photos" ? "Import your photo library." : "Connect a folder.";
  $("#import-dialog").showModal();
  await loadSources();
}
$("#photo-library").onclick = () => showImport("photos");
$("#sidebar-add").onclick = () => showImport("all");
$("#sources-add").onclick = () => showImport("all");
$("#close-import").onclick = () => $("#import-dialog").close();
$("#close-sources").onclick = () => $("#sources-dialog").close();
$("#manage-sources").onclick = async () => {
  await loadSources();
  $("#sources-dialog").showModal();
};
let folderBrowseSequence = 0;
async function browseFolder(path = "") {
  const seq = ++folderBrowseSequence;
  $("#folder-browser").hidden = false;
  $("#folder-browser").setAttribute("aria-busy", "true");
  $("#folder-browser-error").textContent = "";
  $("#browser-select").disabled = true;
  try {
    const data = await api("/api/browse?path=" + encodeURIComponent(path));
    if (seq !== folderBrowseSequence) return;
    $("#browser-path").textContent = data.path;
    $("#browser-up").disabled = data.parent === data.path;
    $("#browser-up").onclick = () => browseFolder(data.parent);
    $("#browser-select").disabled = false;
    $("#browser-select").onclick = () => {
      $("#folder").value = data.path;
      $("#folder-browser").hidden = true;
      $("#folder").focus();
    };
    $("#browser-locations").replaceChildren();
    for (const location of data.locations) {
      const b = text("button", location.name);
      b.type = "button";
      b.onclick = () => browseFolder(location.path);
      $("#browser-locations").append(b);
    }
    $("#browser-folders").replaceChildren();
    for (const folder of data.folders) {
      const b = text("button", "", "folder-row");
      b.type = "button";
      b.append(icon("folder"), text("span", folder.name), text("span", "›"));
      b.onclick = () => browseFolder(folder.path);
      $("#browser-folders").append(b);
    }
    if (!data.folders.length)
      $("#browser-folders").append(
        text("p", "No subfolders. You can choose this folder.", "folder-empty"),
      );
  } catch (error) {
    if (seq === folderBrowseSequence)
      $("#folder-browser-error").textContent = error.message;
  } finally {
    if (seq === folderBrowseSequence)
      $("#folder-browser").setAttribute("aria-busy", "false");
  }
}
$("#browse-folder").onclick = () => browseFolder($("#folder").value.trim());
$("#browser-close").onclick = () => {
  $("#folder-browser").hidden = true;
  folderBrowseSequence++;
};
$("#use-pictures").onclick = async () => {
  try {
    const result = await api("/api/sources");
    $("#folder").value = result.pictures;
    $("#folder").focus();
  } catch (error) {
    $("#import-error").textContent = error.message;
  }
};
async function loadSources() {
  try {
    const data = await api("/api/sources");
    sources = data.sources;
    const signature = JSON.stringify(
      sources.map(({ last_scan, ...rest }) => rest),
    );
    if (signature === lastSources) return;
    lastSources = signature;
    $("#source-list").replaceChildren();
    $("#source-cards").replaceChildren();
    if (!sources.length) {
      $("#source-list").append(
        text(
          "p",
          "Connect a folder to keep your library up to date.",
          "source-empty",
        ),
      );
      $("#source-cards").append(
        text(
          "p",
          "No connected folders yet. Choose one to get started.",
          "sources-empty",
        ),
      );
    }
    for (const source of sources) {
      const nav = text("button", "", "source-nav");
      nav.append(
        icon(source.scope === "photos" ? "photo" : "folder"),
        text("span", source.name),
        text("small", String(source.count)),
      );
      nav.title = source.path;
      nav.onclick = () => {
        sourcePrefix = source.path;
        $("#query").value = "";
        filter = "all";
        setFilter("all");
        search();
      };
      $("#source-list").append(nav);
      const card = text("article", "", "source-card"),
        top = text("div", "", "source-card-top");
      top.append(
        icon(source.scope === "photos" ? "photo" : "folder"),
        text("strong", source.name),
        text(
          "span",
          !source.available
            ? "Unavailable"
            : source.enabled
              ? "Auto-sync on"
              : "Paused",
          "source-state",
        ),
      );
      card.append(
        top,
        text("p", source.path, "source-path"),
        text(
          "small",
          source.count +
            " files · " +
            (source.scope === "photos"
              ? "Photos only"
              : "Photos and documents"),
        ),
      );
      if (source.error) card.append(text("p", source.error, "source-error"));
      const actions = text("div", "", "source-actions");
      for (const [label, route, body] of [
        ["Sync now", "sync", {}],
        [
          source.enabled ? "Pause sync" : "Resume sync",
          "toggle",
          { enabled: !source.enabled },
        ],
        ["Disconnect", "disconnect", {}],
      ]) {
        const b = text("button", label);
        b.onclick = async () => {
          b.disabled = true;
          try {
            await api("/api/source/" + route, { id: source.id, ...body });
            if (route === "sync") wasRunning = true;
            if (route === "disconnect" && sourcePrefix === source.path) {
              sourcePrefix = "";
              render();
            }
            await loadSources();
            await poll();
          } catch (error) {
            message(error.message);
            toast(error.message);
          } finally {
            b.disabled = false;
          }
        };
        actions.append(b);
      }
      card.append(actions);
      $("#source-cards").append(card);
    }
  } catch (error) {
    message(error.message);
  }
}

async function previewURL(result, page, width) {
  const route =
    result.is_image && width <= 720
      ? "/api/image?id=" + result.id
      : "/api/render?id=" + result.id + "&page=" + page + "&width=" + width;
  const key = result.id + ":" + result.version + ":" + page + ":" + width;
  if (!photoCache.has(key)) {
    photoCache.set(
      key,
      request(route)
        .then(async (response) => {
          if (!response.ok) {
            let data = await response.json();
            throw new Error(data.error || "Preview unavailable");
          }
          return URL.createObjectURL(await response.blob());
        })
        .catch((error) => {
          photoCache.delete(key);
          throw error;
        }),
    );
  }
  return photoCache.get(key);
}
async function loadPreview(img, result, page, width) {
  const requestId = result.id + ":" + page + ":" + width;
  img.dataset.previewId = requestId;
  try {
    const url = await previewURL(result, page, width);
    if (img.dataset.previewId === requestId) img.src = url;
  } catch (error) {
    img.alt = "Preview unavailable";
  }
}
function readerView(mode) {
  readerMode = mode;
  const original = mode === "original" && reader?.kind !== "text";
  $("#preview-stage").hidden = !original;
  $("#preview-body").hidden = original;
  $(".reader-label").hidden = original;
  $("#reader-zoom").hidden = !original;
  $("#show-original").classList.toggle("active", original);
  $("#show-text").classList.toggle("active", !original);
}
async function openReader(result, page = result.page) {
  const seq = ++readerSequence;
  if (!reader || reader.id !== result.id)
    readerMode = result.kind === "text" ? "text" : "original";
  reader = { ...result, page };
  $("#preview-title").textContent = result.name;
  $("#preview-path").textContent = result.path;
  $("#reader-status").textContent = "Loading…";
  $("#preview-body").replaceChildren();
  $("#preview-image").hidden = true;
  $("#preview-image").removeAttribute("src");
  $("#preview-image").dataset.previewId = "";
  $("#reader-zoom").value = "100";
  $("#preview-image").style.width = "100%";
  if (!$("#preview").open) $("#preview").showModal();
  try {
    const data = await api("/api/preview?id=" + result.id + "&page=" + page);
    if (seq !== readerSequence) return;
    reader = { ...reader, ...data };
    $("#page-counter").textContent = "Page " + page + " of " + data.page_count;
    $(".reader-pagination").hidden = data.page_count < 2;
    $("#previous-page").disabled = page <= 1;
    $("#next-page").disabled = page >= data.page_count;
    $("#show-original").hidden = data.kind === "text";
    $("#show-text").hidden = data.kind === "image" && !data.body;
    $("#matching-pages").replaceChildren();
    if (result.matching_pages?.length > 1 && $("#query").value.trim()) {
      const label = text("span", "Matches on pages ");
      $("#matching-pages").append(label);
      for (const n of result.matching_pages) {
        const b = text("button", n);
        b.classList.toggle("active", n === page);
        b.onclick = () => openReader(result, n);
        $("#matching-pages").append(b);
      }
    }
    const words = ($("#query").value.match(/\w+/g) || []).filter(
      (w) =>
        !["where", "is", "my", "the", "a", "find", "show", "me"].includes(
          w.toLowerCase(),
        ),
    );
    if (words.length) {
      const pattern = new RegExp("(" + words.join("|") + ")", "gi");
      for (const part of data.body.split(pattern))
        $("#preview-body").append(
          text(
            words.some((w) => part.toLowerCase().startsWith(w.toLowerCase()))
              ? "mark"
              : "span",
            part,
          ),
        );
    } else $("#preview-body").textContent = data.body;
    if (!data.body)
      $("#preview-body").textContent = "No text was detected on this page.";
    readerView(data.kind === "text" ? "text" : readerMode);
    $("#reader-status").textContent = data.available
      ? ""
      : "Original unavailable. Extracted text is still available.";
    if (data.kind !== "text") {
      try {
        const image = await previewURL(result, page, 1600);
        if (seq !== readerSequence) return;
        $("#preview-image").src = image;
        $("#preview-image").hidden = false;
      } catch (error) {
        if (seq !== readerSequence) return;
        $("#reader-status").textContent = error.message;
        readerView("text");
      }
    }
  } catch (error) {
    if (seq === readerSequence) $("#reader-status").textContent = error.message;
  }
}
$("#show-original").onclick = () => readerView("original");
$("#show-text").onclick = () => readerView("text");
$("#previous-page").onclick = () => {
  if (reader?.page > 1) openReader(reader, reader.page - 1);
};
$("#next-page").onclick = () => {
  if (reader && reader.page < reader.page_count)
    openReader(reader, reader.page + 1);
};
$("#reader-zoom").onchange = () =>
  ($("#preview-image").style.width = $("#reader-zoom").value + "%");
