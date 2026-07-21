(() => {
  "use strict";

  const STORAGE_DESIGN = "fluidics-studio-design-v1";
  const STORAGE_SETTINGS = "fluidics-studio-settings-v1";
  const STORAGE_CONNECTION = "fluidics-studio-octoprint-v1";
  const STORAGE_PRINT_CONFIRM = "fluidics-studio-confirm-print-v1";

  const EXAMPLE_DESIGN = {
    version: 1,
    name: "Flow focusing v1",
    shapes: [
      { id: "main-in", type: "line", name: "Carrier inlet", x1: 10, y1: 12.5, x2: 31, y2: 12.5, width: 0.8 },
      { id: "neck", type: "line", name: "Orifice", x1: 31, y1: 12.5, x2: 42, y2: 12.5, width: 0.45 },
      { id: "out", type: "line", name: "Droplet outlet", x1: 42, y1: 12.5, x2: 66, y2: 12.5, width: 1.15 },
      { id: "top-in", type: "line", name: "Top focusing inlet", x1: 35, y1: 3.5, x2: 35, y2: 11.8, width: 0.8 },
      { id: "bottom-in", type: "line", name: "Bottom focusing inlet", x1: 35, y1: 21.5, x2: 35, y2: 13.2, width: 0.8 },
      { id: "p1", type: "circle", name: "Carrier port", cx: 8.5, cy: 12.5, radius: 1.7, width: 0.8, mode: "chamber" },
      { id: "p2", type: "circle", name: "Top port", cx: 35, cy: 2.8, radius: 1.6, width: 0.8, mode: "chamber" },
      { id: "p3", type: "circle", name: "Bottom port", cx: 35, cy: 22.2, radius: 1.6, width: 0.8, mode: "chamber" },
      { id: "p4", type: "circle", name: "Outlet port", cx: 68, cy: 12.5, radius: 1.8, width: 0.8, mode: "chamber" },
    ],
    guides: [
      { id: "guide-1", type: "guide", name: "18 mm coverslip", x: 38.5, y: 12.5, width: 18, height: 18, rotation: 45 },
    ],
  };

  const EMPTY_DESIGN = () => ({ version: 1, name: "Untitled chip", shapes: [], guides: [] });
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const byId = (id) => document.getElementById(id);
  const canvas = byId("designCanvas");
  const stage = byId("slideStage");
  const ctx = canvas.getContext("2d");

  let design = loadDesign();
  let selected = null;
  let activeTool = "select";
  let previewPaths = [];
  let previewStats = null;
  let interaction = null;
  let history = [];
  let future = [];
  let previewTimer = null;
  let previewController = null;
  let previewSequence = 0;

  function uid(prefix = "shape") {
    if (crypto?.randomUUID) return `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
    return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
  }

  function loadDesign() {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_DESIGN));
      if (stored && Array.isArray(stored.shapes)) {
        stored.guides = Array.isArray(stored.guides) ? stored.guides : [];
        return stored;
      }
    } catch (_error) {
      // A damaged local draft should never keep the editor from opening.
    }
    return clone(EXAMPLE_DESIGN);
  }

  function saveDesign() {
    design.name = byId("jobName").value.trim() || "Untitled chip";
    localStorage.setItem(STORAGE_DESIGN, JSON.stringify(design));
    byId("autosaveState").textContent = "Saved locally";
    window.clearTimeout(saveDesign.timer);
    saveDesign.timer = window.setTimeout(() => {
      byId("autosaveState").textContent = "Local autosave on";
    }, 1400);
  }

  function getSettings() {
    const settings = {};
    document.querySelectorAll("[data-setting]").forEach((input) => {
      const key = input.dataset.setting;
      settings[key] = input.type === "checkbox" ? input.checked : Number(input.value);
    });
    return settings;
  }

  function loadSettings() {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_SETTINGS)) || {};
      document.querySelectorAll("[data-setting]").forEach((input) => {
        if (!(input.dataset.setting in stored)) return;
        if (input.type === "checkbox") input.checked = Boolean(stored[input.dataset.setting]);
        else input.value = stored[input.dataset.setting];
      });
    } catch (_error) {
      // Keep the well-tested defaults from the HTML.
    }
  }

  function saveSettings() {
    localStorage.setItem(STORAGE_SETTINGS, JSON.stringify(getSettings()));
  }

  function slideSize() {
    const settings = getSettings();
    return {
      width: Number.isFinite(settings.slide_width) && settings.slide_width > 0 ? settings.slide_width : 75,
      height: Number.isFinite(settings.slide_height) && settings.slide_height > 0 ? settings.slide_height : 25,
    };
  }

  function updateStageAspect() {
    const size = slideSize();
    stage.style.aspectRatio = `${size.width} / ${size.height}`;
  }

  function canvasMetrics() {
    const rect = canvas.getBoundingClientRect();
    const slide = slideSize();
    return { rect, slide, sx: rect.width / slide.width, sy: rect.height / slide.height };
  }

  function resizeCanvas() {
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    draw();
  }

  function mmToPx(point, metrics = canvasMetrics()) {
    return { x: point.x * metrics.sx, y: point.y * metrics.sy };
  }

  function eventPoint(event, applyGrid = true) {
    const { rect, slide } = canvasMetrics();
    let point = {
      x: Math.max(0, Math.min(slide.width, ((event.clientX - rect.left) / rect.width) * slide.width)),
      y: Math.max(0, Math.min(slide.height, ((event.clientY - rect.top) / rect.height) * slide.height)),
    };
    if (applyGrid && byId("gridSnap").checked && activeTool !== "freehand") point = snapToGrid(point);
    return point;
  }

  function snapToGrid(point) {
    const step = Math.max(0.01, Number(byId("gridStep").value) || 1);
    return { x: Math.round(point.x / step) * step, y: Math.round(point.y / step) * step };
  }

  function snapAngle(origin, point, event) {
    if (!byId("angleSnap").checked || !(event.ctrlKey || event.metaKey)) return point;
    const dx = point.x - origin.x;
    const dy = point.y - origin.y;
    const length = Math.hypot(dx, dy);
    const angle = Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) * (Math.PI / 4);
    return { x: origin.x + Math.cos(angle) * length, y: origin.y + Math.sin(angle) * length };
  }

  function draw() {
    const rect = canvas.getBoundingClientRect();
    const dpr = canvas.width / Math.max(1, rect.width);
    const metrics = canvasMetrics();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.fillStyle = "#fbfdfc";
    ctx.fillRect(0, 0, rect.width, rect.height);
    drawGrid(metrics);
    if (byId("showGuides").checked) design.guides.forEach((guide) => drawGuide(guide, metrics));
    design.shapes.forEach((shape) => drawShape(shape, metrics));
    if (interaction?.draft) drawDraft(interaction.draft, metrics);
    if (byId("showPrintPaths").checked) drawPreviewPaths(metrics);
    drawSelection(metrics);
    ctx.strokeStyle = "#9bb0aa";
    ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, rect.width - 1, rect.height - 1);
  }

  function drawGrid(metrics) {
    if (!byId("showGrid").checked) return;
    const step = Math.max(0.1, Number(byId("gridStep").value) || 1);
    ctx.save();
    ctx.font = "8px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textBaseline = "top";
    for (let x = 0; x <= metrics.slide.width + 1e-6; x += step) {
      const px = x * metrics.sx;
      const major = Math.abs(x / 5 - Math.round(x / 5)) < 1e-6;
      ctx.strokeStyle = major ? "rgba(36,78,71,.14)" : "rgba(36,78,71,.055)";
      ctx.lineWidth = major ? 1 : 0.7;
      ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, metrics.rect.height); ctx.stroke();
      if (major && x > 0 && x < metrics.slide.width) {
        ctx.fillStyle = "rgba(45,73,68,.55)";
        ctx.fillText(`${x}`, px + 3, 4);
      }
    }
    for (let y = 0; y <= metrics.slide.height + 1e-6; y += step) {
      const py = y * metrics.sy;
      const major = Math.abs(y / 5 - Math.round(y / 5)) < 1e-6;
      ctx.strokeStyle = major ? "rgba(36,78,71,.14)" : "rgba(36,78,71,.055)";
      ctx.lineWidth = major ? 1 : 0.7;
      ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(metrics.rect.width, py); ctx.stroke();
      if (major && y > 0 && y < metrics.slide.height) {
        ctx.fillStyle = "rgba(45,73,68,.55)";
        ctx.fillText(`${y}`, 4, py + 3);
      }
    }
    ctx.restore();
  }

  function drawGuide(guide, metrics, draft = false) {
    const center = mmToPx({ x: guide.x, y: guide.y }, metrics);
    ctx.save();
    ctx.translate(center.x, center.y);
    ctx.rotate((Number(guide.rotation) || 0) * Math.PI / 180);
    const width = guide.width * metrics.sx;
    const height = guide.height * metrics.sy;
    ctx.fillStyle = draft ? "rgba(104,142,80,.07)" : "rgba(104,142,80,.105)";
    ctx.strokeStyle = selected?.id === guide.id ? "#e96a43" : "#688e50";
    ctx.lineWidth = selected?.id === guide.id ? 2 : 1.2;
    ctx.setLineDash([6, 4]);
    ctx.fillRect(-width / 2, -height / 2, width, height);
    ctx.strokeRect(-width / 2, -height / 2, width, height);
    ctx.setLineDash([]);
    ctx.fillStyle = "#4f733d";
    ctx.font = "700 9px ui-sans-serif, system-ui";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(guide.name || "Coverslip", 0, 0);
    ctx.restore();
  }

  function shapePath(shape, metrics) {
    ctx.beginPath();
    if (shape.type === "line") {
      const a = mmToPx({ x: shape.x1, y: shape.y1 }, metrics);
      const b = mmToPx({ x: shape.x2, y: shape.y2 }, metrics);
      ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
    } else if (shape.type === "freehand") {
      (shape.points || []).forEach((point, index) => {
        const px = mmToPx({ x: point[0], y: point[1] }, metrics);
        if (index === 0) ctx.moveTo(px.x, px.y); else ctx.lineTo(px.x, px.y);
      });
    } else if (shape.type === "arc") {
      const c = mmToPx({ x: shape.cx, y: shape.cy }, metrics);
      const start = Number(shape.startAngle) * Math.PI / 180;
      const end = (Number(shape.startAngle) + Number(shape.sweepAngle)) * Math.PI / 180;
      ctx.ellipse(c.x, c.y, shape.radius * metrics.sx, shape.radius * metrics.sy, 0, start, end, shape.sweepAngle < 0);
    } else if (shape.type === "circle") {
      const c = mmToPx({ x: shape.cx, y: shape.cy }, metrics);
      ctx.ellipse(c.x, c.y, shape.radius * metrics.sx, shape.radius * metrics.sy, 0, 0, Math.PI * 2);
    }
  }

  function drawShape(shape, metrics, draft = false) {
    ctx.save();
    shapePath(shape, metrics);
    const selectedShape = selected?.id === shape.id;
    const widthPx = Math.max(1, Number(shape.width || 0.75) * (metrics.sx + metrics.sy) / 2);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    if (shape.type === "circle" && shape.mode !== "ring") {
      ctx.fillStyle = draft ? "rgba(16,139,137,.28)" : "rgba(16,139,137,.46)";
      ctx.fill();
      ctx.strokeStyle = selectedShape ? "#e96a43" : "rgba(6,103,99,.8)";
      ctx.lineWidth = selectedShape ? 2 : 1;
      ctx.stroke();
    } else {
      ctx.strokeStyle = draft ? "rgba(16,139,137,.4)" : "rgba(16,139,137,.5)";
      ctx.lineWidth = widthPx;
      ctx.stroke();
      ctx.strokeStyle = selectedShape ? "#e96a43" : "rgba(7,107,104,.8)";
      ctx.lineWidth = selectedShape ? 2 : 1;
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawDraft(draft, metrics) {
    if (draft.type === "guide") drawGuide(draft, metrics, true);
    else drawShape(draft, metrics, true);
  }

  function drawPreviewPaths(metrics) {
    const settings = getSettings();
    const lineWidth = Math.max(1.25, Number(settings.extrusion_line_width || 0.45) * (metrics.sx + metrics.sy) / 2);
    ctx.save();
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    previewPaths.forEach((path) => {
      if (!path.points?.length) return;
      ctx.beginPath();
      path.points.forEach((point, index) => {
        const px = mmToPx({ x: point[0], y: point[1] }, metrics);
        if (index === 0) ctx.moveTo(px.x, px.y); else ctx.lineTo(px.x, px.y);
      });
      ctx.strokeStyle = path.kind === "brim" ? "rgba(224,146,29,.82)" : "rgba(240,91,61,.92)";
      ctx.lineWidth = lineWidth;
      ctx.stroke();
      ctx.strokeStyle = "rgba(255,255,255,.88)";
      ctx.lineWidth = Math.max(.7, lineWidth * .22);
      ctx.stroke();
    });
    previewPaths.forEach((path) => {
      [path.leadIn, path.leadOut].forEach((segment) => {
        if (!segment?.length) return;
        const start = mmToPx({ x: segment[0][0], y: segment[0][1] }, metrics);
        const end = mmToPx({ x: segment[1][0], y: segment[1][1] }, metrics);
        ctx.beginPath(); ctx.moveTo(start.x, start.y); ctx.lineTo(end.x, end.y);
        ctx.strokeStyle = "rgba(111,62,151,.96)";
        ctx.lineWidth = Math.max(1.6, lineWidth * .72);
        ctx.stroke();
      });
      if (path.leadIn?.length) {
        const entry = mmToPx({ x: path.leadIn[0][0], y: path.leadIn[0][1] }, metrics);
        ctx.fillStyle = "#6f3e97";
        ctx.beginPath(); ctx.arc(entry.x, entry.y, Math.max(2.5, lineWidth * .65), 0, Math.PI * 2); ctx.fill();
      }
    });
    ctx.restore();
  }

  function selectedItem() {
    if (!selected) return null;
    const list = selected.collection === "guides" ? design.guides : design.shapes;
    return list.find((item) => item.id === selected.id) || null;
  }

  function drawSelection(metrics) {
    const item = selectedItem();
    if (!item) return;
    const handles = selectionHandles(item);
    ctx.save();
    handles.forEach((point) => {
      const px = mmToPx(point, metrics);
      ctx.fillStyle = "#ffffff";
      ctx.strokeStyle = "#e96a43";
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(px.x, px.y, 4, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    });
    ctx.restore();
  }

  function selectionHandles(item) {
    if (item.type === "line") return [{ x: item.x1, y: item.y1 }, { x: item.x2, y: item.y2 }];
    if (item.type === "freehand") {
      if (!item.points?.length) return [];
      return [item.points[0], item.points[item.points.length - 1]].map(([x, y]) => ({ x, y }));
    }
    if (item.type === "circle") return [{ x: item.cx + item.radius, y: item.cy }];
    if (item.type === "arc") {
      const angle = (item.startAngle + item.sweepAngle) * Math.PI / 180;
      return [{ x: item.cx, y: item.cy }, { x: item.cx + item.radius * Math.cos(angle), y: item.cy + item.radius * Math.sin(angle) }];
    }
    if (item.type === "guide") return [{ x: item.x, y: item.y }];
    return [];
  }

  function pointSegmentDistance(point, a, b) {
    const dx = b.x - a.x, dy = b.y - a.y;
    if (dx === 0 && dy === 0) return Math.hypot(point.x - a.x, point.y - a.y);
    const t = Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / (dx * dx + dy * dy)));
    return Math.hypot(point.x - (a.x + t * dx), point.y - (a.y + t * dy));
  }

  function arcPoints(shape, count = 48) {
    const steps = Math.max(12, Math.ceil(Math.abs(shape.sweepAngle) / 360 * count));
    return Array.from({ length: steps + 1 }, (_, index) => {
      const angle = (shape.startAngle + shape.sweepAngle * index / steps) * Math.PI / 180;
      return { x: shape.cx + shape.radius * Math.cos(angle), y: shape.cy + shape.radius * Math.sin(angle) };
    });
  }

  function hitShape(shape, point) {
    const tolerance = 0.65 + Number(shape.width || .75) / 2;
    if (shape.type === "line") return pointSegmentDistance(point, { x: shape.x1, y: shape.y1 }, { x: shape.x2, y: shape.y2 }) <= tolerance;
    if (shape.type === "freehand") {
      const points = (shape.points || []).map(([x, y]) => ({ x, y }));
      return points.some((current, index) => index && pointSegmentDistance(point, points[index - 1], current) <= tolerance);
    }
    if (shape.type === "circle") {
      const radial = Math.hypot(point.x - shape.cx, point.y - shape.cy);
      return shape.mode === "ring" ? Math.abs(radial - shape.radius) <= tolerance : radial <= shape.radius + .55;
    }
    if (shape.type === "arc") {
      const points = arcPoints(shape);
      return points.some((current, index) => index && pointSegmentDistance(point, points[index - 1], current) <= tolerance);
    }
    return false;
  }

  function hitGuide(guide, point) {
    const angle = -(guide.rotation || 0) * Math.PI / 180;
    const dx = point.x - guide.x, dy = point.y - guide.y;
    const x = dx * Math.cos(angle) - dy * Math.sin(angle);
    const y = dx * Math.sin(angle) + dy * Math.cos(angle);
    const edge = Math.min(Math.abs(Math.abs(x) - guide.width / 2), Math.abs(Math.abs(y) - guide.height / 2));
    const inside = Math.abs(x) <= guide.width / 2 && Math.abs(y) <= guide.height / 2;
    return inside && edge <= 1.1;
  }

  function hitTest(point) {
    for (let index = design.shapes.length - 1; index >= 0; index--) {
      if (hitShape(design.shapes[index], point)) return { collection: "shapes", id: design.shapes[index].id };
    }
    if (byId("showGuides").checked) {
      for (let index = design.guides.length - 1; index >= 0; index--) {
        if (hitGuide(design.guides[index], point)) return { collection: "guides", id: design.guides[index].id };
      }
    }
    return null;
  }

  function remember(snapshot = clone(design)) {
    history.push(snapshot);
    if (history.length > 80) history.shift();
    future = [];
    updateUndoButtons();
  }

  function commit(mutator) {
    remember();
    mutator();
    afterDesignChange();
  }

  function afterDesignChange() {
    saveDesign();
    renderInspector();
    draw();
    schedulePreview();
    updateUndoButtons();
  }

  function updateUndoButtons() {
    byId("undoButton").disabled = history.length === 0;
    byId("redoButton").disabled = future.length === 0;
  }

  function undo() {
    if (!history.length) return;
    future.push(clone(design));
    design = history.pop();
    selected = null;
    byId("jobName").value = design.name || "Untitled chip";
    afterDesignChange();
  }

  function redo() {
    if (!future.length) return;
    history.push(clone(design));
    design = future.pop();
    selected = null;
    byId("jobName").value = design.name || "Untitled chip";
    afterDesignChange();
  }

  function translateItem(target, original, dx, dy) {
    if (target.type === "line") {
      target.x1 = original.x1 + dx; target.y1 = original.y1 + dy;
      target.x2 = original.x2 + dx; target.y2 = original.y2 + dy;
    } else if (target.type === "freehand") {
      target.points = original.points.map(([x, y]) => [x + dx, y + dy]);
    } else if (target.type === "circle" || target.type === "arc") {
      target.cx = original.cx + dx; target.cy = original.cy + dy;
    } else if (target.type === "guide") {
      target.x = original.x + dx; target.y = original.y + dy;
    }
  }

  function onPointerDown(event) {
    if (event.button !== 0) return;
    canvas.focus();
    canvas.setPointerCapture(event.pointerId);
    const point = eventPoint(event, activeTool !== "freehand");
    if (activeTool === "select") {
      const hit = hitTest(point);
      selected = hit;
      renderInspector();
      draw();
      if (hit) {
        interaction = {
          mode: "move",
          start: point,
          before: clone(design),
          original: clone(selectedItem()),
          changed: false,
        };
      }
      return;
    }
    const width = Math.max(.05, Number(byId("defaultWidth").value) || .75);
    if (activeTool === "line") {
      interaction = { mode: "draw", start: point, draft: { id: uid(), type: "line", name: "Straight channel", x1: point.x, y1: point.y, x2: point.x, y2: point.y, width } };
    } else if (activeTool === "freehand") {
      interaction = { mode: "draw", start: point, draft: { id: uid(), type: "freehand", name: "Freehand channel", points: [[point.x, point.y]], width } };
    } else if (activeTool === "arc") {
      interaction = { mode: "draw", start: point, draft: { id: uid(), type: "arc", name: "Circular arc", cx: point.x, cy: point.y, radius: 0, startAngle: 0, sweepAngle: Number(byId("defaultArcSweep").value) || 90, width } };
    } else if (activeTool === "circle") {
      interaction = { mode: "draw", start: point, draft: { id: uid(), type: "circle", name: byId("defaultCircleMode").value === "ring" ? "Circular channel" : "Circular chamber", cx: point.x, cy: point.y, radius: 0, width, mode: byId("defaultCircleMode").value } };
    } else if (activeTool === "guide") {
      interaction = { mode: "draw", start: point, draft: { id: uid("guide"), type: "guide", name: "Coverslip guide", x: point.x, y: point.y, width: 0, height: 0, rotation: 0 } };
    }
    draw();
  }

  function onPointerMove(event) {
    const raw = eventPoint(event, false);
    byId("cursorPosition").textContent = `x ${raw.x.toFixed(2)} · y ${raw.y.toFixed(2)} mm`;
    if (!interaction) {
      if (activeTool === "select") canvas.style.cursor = hitTest(raw) ? "grab" : "default";
      return;
    }
    if (interaction.mode === "move") {
      const point = byId("gridSnap").checked ? snapToGrid(raw) : raw;
      const target = selectedItem();
      if (!target) return;
      translateItem(target, interaction.original, point.x - interaction.start.x, point.y - interaction.start.y);
      interaction.changed = true;
      canvas.style.cursor = "grabbing";
      draw();
      renderInspector();
      return;
    }
    const draft = interaction.draft;
    if (draft.type === "line") {
      let point = eventPoint(event, true);
      point = snapAngle(interaction.start, point, event);
      draft.x2 = point.x; draft.y2 = point.y;
    } else if (draft.type === "freehand") {
      const previous = draft.points[draft.points.length - 1];
      if (Math.hypot(raw.x - previous[0], raw.y - previous[1]) >= .12) draft.points.push([raw.x, raw.y]);
    } else if (draft.type === "circle") {
      draft.radius = Math.hypot(raw.x - draft.cx, raw.y - draft.cy);
    } else if (draft.type === "arc") {
      const point = eventPoint(event, true);
      draft.radius = Math.hypot(point.x - draft.cx, point.y - draft.cy);
      draft.startAngle = Math.atan2(point.y - draft.cy, point.x - draft.cx) * 180 / Math.PI;
    } else if (draft.type === "guide") {
      const point = eventPoint(event, true);
      draft.x = (interaction.start.x + point.x) / 2;
      draft.y = (interaction.start.y + point.y) / 2;
      draft.width = Math.abs(point.x - interaction.start.x);
      draft.height = Math.abs(point.y - interaction.start.y);
    }
    draw();
  }

  function onPointerUp(event) {
    if (!interaction) return;
    if (interaction.mode === "move") {
      if (interaction.changed) {
        remember(interaction.before);
        afterDesignChange();
      }
      interaction = null;
      canvas.style.cursor = "default";
      return;
    }
    const draft = interaction.draft;
    interaction = null;
    let valid = false;
    if (draft.type === "line") valid = Math.hypot(draft.x2 - draft.x1, draft.y2 - draft.y1) > .1;
    else if (draft.type === "freehand") valid = draft.points.length > 1;
    else if (draft.type === "circle" || draft.type === "arc") valid = draft.radius > .1;
    else if (draft.type === "guide") valid = draft.width > .2 && draft.height > .2;
    if (!valid) { draw(); return; }
    commit(() => {
      if (draft.type === "guide") {
        design.guides.push(draft);
        selected = { collection: "guides", id: draft.id };
      } else {
        design.shapes.push(draft);
        selected = { collection: "shapes", id: draft.id };
      }
    });
    setTool("select");
  }

  function setTool(tool) {
    activeTool = tool;
    document.querySelectorAll("[data-tool]").forEach((button) => button.classList.toggle("active", button.dataset.tool === tool));
    const hints = {
      select: "Click to select; drag to move. Delete removes a selection.",
      line: "Drag a straight channel. Hold Ctrl or ⌘ to snap to 45° increments.",
      freehand: "Draw a continuous freehand channel; the fabrication preview smooths its contour.",
      arc: "Drag from the arc center to set radius and start angle. Set sweep at right.",
      circle: "Drag from center to radius. Choose a chamber or circular channel at right.",
      guide: "Drag a non-printing reference rectangle, or add a dimensioned coverslip at right.",
    };
    byId("toolHint").textContent = hints[tool];
    canvas.style.cursor = tool === "select" ? "default" : "crosshair";
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
  }

  function numberField(label, property, value, unit = "mm", step = ".1") {
    return `<label class="field"><span>${label}</span><div class="unit-input"><input data-selection-prop="${property}" type="number" value="${Number(value).toFixed(step === ".01" ? 2 : 3).replace(/0+$/, "").replace(/\.$/, "")}" step="${step}"><i>${unit}</i></div></label>`;
  }

  function renderInspector() {
    const item = selectedItem();
    byId("selectionEmpty").hidden = Boolean(item);
    byId("selectionFields").hidden = !item;
    byId("selectionKind").textContent = item ? item.type.toUpperCase() : "NONE";
    if (!item) {
      byId("selectionFields").innerHTML = "";
      return;
    }
    let fields = `<div class="selection-title-row"><input data-selection-prop="name" value="${escapeHtml(item.name || "")}" aria-label="Selection name"><button class="mini-delete" data-selection-delete title="Delete">×</button></div>`;
    if (item.type === "line") {
      fields += `<div class="field-grid two-up">${numberField("Start X", "x1", item.x1)}${numberField("Start Y", "y1", item.y1)}${numberField("End X", "x2", item.x2)}${numberField("End Y", "y2", item.y2)}${numberField("Channel width", "width", item.width, "mm", ".05")}</div>`;
      fields += `<div class="selection-derived">Length <strong>${Math.hypot(item.x2 - item.x1, item.y2 - item.y1).toFixed(2)} mm</strong></div>`;
    } else if (item.type === "freehand") {
      fields += numberField("Channel width", "width", item.width, "mm", ".05");
      fields += `<div class="selection-derived">Sample points <strong>${item.points.length}</strong></div>`;
    } else if (item.type === "circle") {
      fields += `<div class="field-grid two-up">${numberField("Center X", "cx", item.cx)}${numberField("Center Y", "cy", item.cy)}${numberField("Radius", "radius", item.radius)}${numberField("Channel width", "width", item.width, "mm", ".05")}</div>`;
      fields += `<label class="field"><span>Circle behavior</span><select data-selection-prop="mode"><option value="chamber"${item.mode !== "ring" ? " selected" : ""}>Filled chamber</option><option value="ring"${item.mode === "ring" ? " selected" : ""}>Circular channel</option></select></label>`;
    } else if (item.type === "arc") {
      fields += `<div class="field-grid two-up">${numberField("Center X", "cx", item.cx)}${numberField("Center Y", "cy", item.cy)}${numberField("Radius", "radius", item.radius)}${numberField("Start angle", "startAngle", item.startAngle, "°", "1")}${numberField("Sweep", "sweepAngle", item.sweepAngle, "°", "1")}${numberField("Channel width", "width", item.width, "mm", ".05")}</div>`;
    } else if (item.type === "guide") {
      fields += `<div class="field-grid two-up">${numberField("Center X", "x", item.x)}${numberField("Center Y", "y", item.y)}${numberField("Width", "width", item.width)}${numberField("Height", "height", item.height)}${numberField("Rotation", "rotation", item.rotation, "°", "1")}</div>`;
    }
    byId("selectionFields").innerHTML = fields;
  }

  function deleteSelected() {
    if (!selectedItem()) return;
    commit(() => {
      const list = selected.collection === "guides" ? design.guides : design.shapes;
      const index = list.findIndex((item) => item.id === selected.id);
      if (index >= 0) list.splice(index, 1);
      selected = null;
    });
  }

  function duplicateSelected() {
    const item = selectedItem();
    if (!item) return;
    commit(() => {
      const copy = clone(item);
      copy.id = uid(item.type === "guide" ? "guide" : "shape");
      copy.name = `${copy.name || copy.type} copy`;
      translateItem(copy, clone(copy), 1, 1);
      const collection = item.type === "guide" ? "guides" : "shapes";
      design[collection].push(copy);
      selected = { collection, id: copy.id };
    });
  }

  function previewPayload() {
    design.name = byId("jobName").value.trim() || "Untitled chip";
    return { name: design.name, design, settings: getSettings() };
  }

  function schedulePreview() {
    window.clearTimeout(previewTimer);
    setPreviewStatus("Updating preview", "Vector design changed", false);
    previewTimer = window.setTimeout(updatePreview, 260);
  }

  async function updatePreview() {
    if (previewController) previewController.abort();
    previewController = new AbortController();
    const sequence = ++previewSequence;
    try {
      const response = await fetch("/api/slice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(previewPayload()),
        signal: previewController.signal,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not build the preview");
      if (sequence !== previewSequence) return;
      previewPaths = result.paths || [];
      previewStats = result.stats;
      updateStats(result.stats);
      const warning = result.warnings?.[0];
      setPreviewStatus("Fabrication preview ready", warning || "Contours rebuilt from the current design", false);
      draw();
    } catch (error) {
      if (error.name === "AbortError") return;
      previewPaths = [];
      previewStats = null;
      updateStats(null);
      setPreviewStatus("Preview needs attention", error.message, true);
      draw();
    }
  }

  function setPreviewStatus(title, detail, error) {
    byId("previewStatus").textContent = title;
    byId("previewWarnings").textContent = detail;
    document.querySelector(".job-summary").classList.toggle("error", Boolean(error));
  }

  function updateStats(stats) {
    byId("statPaths").textContent = stats ? stats.pathCount : "—";
    byId("statLength").textContent = stats ? `${stats.pathLengthMm.toFixed(1)} mm` : "—";
    byId("statFilament").textContent = stats ? `${stats.filamentMm.toFixed(2)} mm` : "—";
    byId("statTime").textContent = stats ? `${Math.max(stats.estimatedMinutes, .01).toFixed(2)} min` : "—";
    byId("modalJobStats").textContent = stats ? `${stats.pathCount} paths · ${stats.pathLengthMm.toFixed(1)} mm` : "Preview unavailable";
  }

  function toast(message, type = "") {
    const node = document.createElement("div");
    node.className = `toast ${type}`;
    node.textContent = message;
    byId("toastStack").appendChild(node);
    window.setTimeout(() => node.remove(), 3600);
  }

  function slugName(name) {
    return (name || "fluidics-slide").trim().replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^[.-]+|[.-]+$/g, "").slice(0, 80) || "fluidics-slide";
  }

  async function downloadGcode() {
    const button = byId("downloadButton");
    button.disabled = true;
    try {
      const response = await fetch("/api/gcode", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(previewPayload()) });
      if (!response.ok) {
        const result = await response.json();
        throw new Error(result.error || "Could not generate G-code");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = `${slugName(design.name)}.gcode`; link.click();
      URL.revokeObjectURL(url);
      toast("G-code downloaded. Verify it before moving to the printer.");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  function exportDesign() {
    const payload = { format: "fluidics-studio", version: 1, design: { ...design, name: byId("jobName").value.trim() || design.name }, settings: getSettings() };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = `${slugName(payload.design.name)}.fluidics.json`; link.click();
    URL.revokeObjectURL(url);
    toast("Design and fabrication settings exported.");
  }

  async function importDesign(file) {
    try {
      const payload = JSON.parse(await file.text());
      const imported = payload.design || payload;
      if (!imported || !Array.isArray(imported.shapes)) throw new Error("This is not a Fluidics Studio design file");
      remember();
      design = { version: 1, name: imported.name || file.name.replace(/\.[^.]+$/, ""), shapes: imported.shapes, guides: Array.isArray(imported.guides) ? imported.guides : [] };
      if (payload.settings) {
        document.querySelectorAll("[data-setting]").forEach((input) => {
          if (!(input.dataset.setting in payload.settings)) return;
          if (input.type === "checkbox") input.checked = Boolean(payload.settings[input.dataset.setting]);
          else input.value = payload.settings[input.dataset.setting];
        });
        saveSettings();
      }
      selected = null;
      byId("jobName").value = design.name;
      updateStageAspect();
      afterDesignChange();
      toast("Design imported.");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      byId("importInput").value = "";
    }
  }

  function loadConnection() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_CONNECTION)) || {};
      byId("octoprintUrl").value = saved.url || "";
      byId("octoprintKey").value = saved.apiKey || "";
    } catch (_error) { /* use blank connection */ }
  }

  function connectionDetails() {
    return { url: byId("octoprintUrl").value.trim(), apiKey: byId("octoprintKey").value.trim() };
  }

  function saveConnection() {
    localStorage.setItem(STORAGE_CONNECTION, JSON.stringify(connectionDetails()));
  }

  function setConnectionStatus(kind, title, detail) {
    const node = byId("connectionStatus");
    node.className = `connection-status ${kind}`;
    node.querySelector("strong").textContent = title;
    node.querySelector("small").textContent = detail;
  }

  async function testConnection() {
    const details = connectionDetails();
    saveConnection();
    setConnectionStatus("idle", "Connecting…", "Contacting the OctoPrint API");
    byId("testConnectionButton").disabled = true;
    try {
      const response = await fetch("/api/octoprint/test", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(details) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Connection failed");
      setConnectionStatus("connected", result.state || "Connected", "OctoPrint accepted the API key");
      toast(`OctoPrint connected: ${result.state || "ready"}.`);
    } catch (error) {
      setConnectionStatus("error", "Connection failed", error.message);
    } finally {
      byId("testConnectionButton").disabled = false;
    }
  }

  async function sendToOctoprint(action) {
    const details = connectionDetails();
    saveConnection();
    const button = action === "upload"
      ? byId("uploadButton")
      : action === "select"
        ? byId("uploadSelectButton")
        : byId("printModal").hidden
          ? byId("printButton")
          : byId("confirmPrintButton");
    const complexButton = button === byId("printButton");
    const oldText = button.textContent;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    if (!complexButton) button.textContent = action === "print" ? "Starting…" : "Sending…";
    try {
      const response = await fetch("/api/octoprint/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...previewPayload(), ...details, action }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "OctoPrint rejected the job");
      setConnectionStatus("connected", action === "print" ? "Print started" : "Job uploaded", `${slugName(design.name)}.gcode`);
      toast(action === "print" ? "Print started in OctoPrint." : action === "select" ? "Job uploaded and selected." : "Job uploaded to OctoPrint.");
      closePrintModal();
    } catch (error) {
      setConnectionStatus("error", "Send failed", error.message);
      toast(error.message, "error");
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      if (!complexButton) button.textContent = oldText;
    }
  }

  function openPrintModal() {
    byId("modalJobName").textContent = `${slugName(byId("jobName").value)}.gcode`;
    byId("printConfirmed").checked = false;
    byId("skipPrintConfirmation").checked = false;
    byId("confirmPrintButton").disabled = true;
    byId("printModal").hidden = false;
  }

  function closePrintModal() {
    byId("printModal").hidden = true;
  }

  function loadPrintConfirmationPreference() {
    byId("confirmBeforePrint").checked = localStorage.getItem(STORAGE_PRINT_CONFIRM) !== "false";
  }

  function startPrint() {
    if (byId("confirmBeforePrint").checked) openPrintModal();
    else sendToOctoprint("print");
  }

  function setupEvents() {
    document.querySelectorAll("[data-tool]").forEach((button) => button.addEventListener("click", () => setTool(button.dataset.tool)));
    document.querySelectorAll(".inspector-tab").forEach((tab) => tab.addEventListener("click", () => {
      document.querySelectorAll(".inspector-tab").forEach((item) => item.classList.toggle("active", item === tab));
      document.querySelectorAll(".inspector-panel").forEach((panel) => panel.classList.toggle("active", panel.id === tab.dataset.panel));
    }));
    document.querySelectorAll("[data-arc-preset]").forEach((button) => button.addEventListener("click", () => { byId("defaultArcSweep").value = button.dataset.arcPreset; }));

    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointercancel", () => { interaction = null; draw(); });
    canvas.addEventListener("pointerleave", () => { if (!interaction) byId("cursorPosition").textContent = "x — · y — mm"; });

    byId("selectionFields").addEventListener("change", (event) => {
      const input = event.target.closest("[data-selection-prop]");
      if (!input || !selectedItem()) return;
      const property = input.dataset.selectionProp;
      const value = input.type === "number" ? Number(input.value) : input.value;
      commit(() => { selectedItem()[property] = value; });
    });
    byId("selectionFields").addEventListener("click", (event) => {
      if (event.target.closest("[data-selection-delete]")) deleteSelected();
    });

    byId("addGuideButton").addEventListener("click", () => {
      const slide = slideSize();
      const guide = {
        id: uid("guide"), type: "guide", name: byId("guideLabel").value.trim() || "Coverslip",
        x: slide.width / 2, y: slide.height / 2,
        width: Math.max(.1, Number(byId("guideWidth").value) || 18),
        height: Math.max(.1, Number(byId("guideHeight").value) || 18),
        rotation: Number(byId("guideRotation").value) || 0,
      };
      commit(() => { design.guides.push(guide); selected = { collection: "guides", id: guide.id }; });
    });

    ["showGrid", "showGuides", "showPrintPaths", "gridStep"].forEach((id) => byId(id).addEventListener("input", draw));
    document.querySelectorAll("[data-setting]").forEach((input) => input.addEventListener("input", () => {
      saveSettings(); updateStageAspect(); draw(); schedulePreview();
    }));
    byId("jobName").addEventListener("input", () => {
      design.name = byId("jobName").value;
      byId("sendJobName").textContent = `${slugName(design.name)}.gcode`;
      saveDesign();
    });

    byId("undoButton").addEventListener("click", undo);
    byId("redoButton").addEventListener("click", redo);
    byId("deleteButton").addEventListener("click", deleteSelected);
    byId("downloadButton").addEventListener("click", downloadGcode);
    byId("exportButton").addEventListener("click", exportDesign);
    byId("importButton").addEventListener("click", () => byId("importInput").click());
    byId("importInput").addEventListener("change", () => { if (byId("importInput").files[0]) importDesign(byId("importInput").files[0]); });
    byId("newButton").addEventListener("click", () => {
      if (design.shapes.length && !window.confirm("Start a blank design? Your current draft is already saved locally and can be exported first.")) return;
      remember(); design = EMPTY_DESIGN(); selected = null; byId("jobName").value = design.name; afterDesignChange();
    });
    byId("exampleButton").addEventListener("click", () => {
      if (design.shapes.length && !window.confirm("Replace the current design with the flow-focusing example?")) return;
      remember(); design = clone(EXAMPLE_DESIGN); selected = null; byId("jobName").value = design.name; afterDesignChange();
    });

    ["octoprintUrl", "octoprintKey"].forEach((id) => byId(id).addEventListener("change", saveConnection));
    byId("showKeyButton").addEventListener("click", () => {
      const input = byId("octoprintKey");
      input.type = input.type === "password" ? "text" : "password";
      byId("showKeyButton").textContent = input.type === "password" ? "Show" : "Hide";
    });
    byId("testConnectionButton").addEventListener("click", testConnection);
    byId("uploadButton").addEventListener("click", () => sendToOctoprint("upload"));
    byId("uploadSelectButton").addEventListener("click", () => sendToOctoprint("select"));
    byId("printButton").addEventListener("click", startPrint);
    byId("confirmBeforePrint").addEventListener("change", () => {
      localStorage.setItem(STORAGE_PRINT_CONFIRM, String(byId("confirmBeforePrint").checked));
    });
    byId("printConfirmed").addEventListener("change", () => { byId("confirmPrintButton").disabled = !byId("printConfirmed").checked; });
    byId("confirmPrintButton").addEventListener("click", () => {
      if (byId("skipPrintConfirmation").checked) {
        byId("confirmBeforePrint").checked = false;
        localStorage.setItem(STORAGE_PRINT_CONFIRM, "false");
      }
      sendToOctoprint("print");
    });
    ["closePrintModal", "cancelPrintButton"].forEach((id) => byId(id).addEventListener("click", closePrintModal));
    byId("printModal").addEventListener("click", (event) => { if (event.target === byId("printModal")) closePrintModal(); });

    window.addEventListener("keydown", (event) => {
      const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault(); event.shiftKey ? redo() : undo(); return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "y") { event.preventDefault(); redo(); return; }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "d" && !typing) { event.preventDefault(); duplicateSelected(); return; }
      if (typing) return;
      if (event.key === "Delete" || event.key === "Backspace") { event.preventDefault(); deleteSelected(); return; }
      if (event.key === "Escape") { interaction = null; selected = null; closePrintModal(); renderInspector(); draw(); return; }
      const shortcut = { v: "select", l: "line", f: "freehand", a: "arc", c: "circle", g: "guide" }[event.key.toLowerCase()];
      if (shortcut) setTool(shortcut);
    });

    new ResizeObserver(resizeCanvas).observe(stage);
  }

  function init() {
    loadSettings();
    loadConnection();
    loadPrintConfirmationPreference();
    byId("jobName").value = design.name || "Untitled chip";
    byId("sendJobName").textContent = `${slugName(design.name)}.gcode`;
    updateStageAspect();
    setupEvents();
    updateUndoButtons();
    renderInspector();
    resizeCanvas();
    schedulePreview();
  }

  init();
})();
