const modelRow = document.querySelector("#model-row");
const cameraPanel = document.querySelector("#camera-panel");
const video = document.querySelector("#video");
const previewWrap = document.querySelector("#preview-wrap");
const preview = document.querySelector("#preview");
const previewName = document.querySelector("#preview-name");
const analyzeButton = document.querySelector("#btn-analyze");
const statusNode = document.querySelector("#status");
const resultCard = document.querySelector("#result");
const fileUpload = document.querySelector("#file-upload");
const fileCapture = document.querySelector("#file-capture");

let selectedModel = "";
let photoBlob = null;
let previewUrl = "";
let stream = null;
let facingMode = "environment";

function setStatus(text, isError = false) {
  statusNode.textContent = text;
  statusNode.classList.toggle("error", isError);
}

function canLiveCamera() {
  return window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia;
}

function stopCamera() {
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }
  video.srcObject = null;
  cameraPanel.hidden = true;
}

async function startCamera() {
  stopCamera();
  stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: { facingMode },
  });
  video.srcObject = stream;
  cameraPanel.hidden = false;
}

function usePhoto(blob, name) {
  photoBlob = blob;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(blob);
  preview.src = previewUrl;
  previewWrap.hidden = false;
  previewName.textContent = name;
  analyzeButton.disabled = false;
  resultCard.hidden = true;
  setStatus("照片已就绪，可以开始识别。");
}

async function blobFromFile(file) {
  try {
    const bitmap = await createImageBitmap(file);
    const maxSide = 1600;
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    if (blob) return blob;
  } catch (_error) {
    // 浏览器解不开的格式交给后端再试一次。
  }
  return file;
}

async function renderModels() {
  const response = await fetch("/api/models");
  const data = await response.json();
  modelRow.replaceChildren();
  data.models.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.role = "radio";
    button.textContent = item.ready ? item.label : `${item.label} · 未配置`;
    button.disabled = !item.ready;
    button.title = item.hint || item.model;
    button.setAttribute("aria-checked", "false");
    button.addEventListener("click", () => selectModel(item.id));
    button.dataset.id = item.id;
    modelRow.appendChild(button);
    if (!selectedModel && item.ready) selectedModel = item.id;
  });
  const missing = data.models.filter((item) => !item.ready).map((item) => item.hint);
  document.querySelector("#model-hint").textContent = missing.join("；");
  if (!selectedModel) {
    setStatus("还没有可用模型。请在 .env 填写 DASHSCOPE_API_KEY 或 DEEPSEEK_API_KEY 后重启。", true);
  }
  selectModel(selectedModel);
}

function selectModel(modelId) {
  selectedModel = modelId;
  modelRow.querySelectorAll(".chip").forEach((chip) => {
    chip.setAttribute("aria-checked", chip.dataset.id === modelId ? "true" : "false");
  });
}

function showResult(data) {
  const badge = document.querySelector("#risk-badge");
  badge.textContent = data.risk_level;
  badge.className = `badge ${data.risk_level}`;
  document.querySelector("#model-used").textContent = `${data.model_label} · ${data.model_name}`;
  document.querySelector("#summary").textContent = data.summary || "";

  const evidence = document.querySelector("#evidence");
  evidence.replaceChildren();
  (data.evidence || []).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    evidence.appendChild(li);
  });

  const suggestion = document.querySelector("#suggestion");
  suggestion.textContent = data.suggestion ? `建议：${data.suggestion}` : "";
  resultCard.hidden = false;
  resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

document.querySelector("#btn-camera").addEventListener("click", async () => {
  if (!canLiveCamera()) {
    setStatus("当前页面不是安全连接，已改用系统相机拍照。");
    fileCapture.click();
    return;
  }
  try {
    await startCamera();
    setStatus("对准楼道后点击拍摄。");
  } catch (_error) {
    setStatus("浏览器没有打开摄像头，已改用系统相机。", true);
    fileCapture.click();
  }
});

document.querySelector("#btn-shot").addEventListener("click", async () => {
  if (!video.videoWidth) {
    setStatus("摄像头还没准备好。", true);
    return;
  }
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
  stopCamera();
  usePhoto(blob, "摄像头拍摄");
});

document.querySelector("#btn-switch").addEventListener("click", async () => {
  facingMode = facingMode === "environment" ? "user" : "environment";
  try {
    await startCamera();
  } catch (_error) {
    setStatus("这个镜头不可用。", true);
  }
});

document.querySelector("#btn-close-cam").addEventListener("click", () => {
  stopCamera();
  setStatus("");
});

document.querySelector("#btn-upload").addEventListener("click", () => fileUpload.click());

async function onPickedFile(event) {
  const file = event.target.files && event.target.files[0];
  event.target.value = "";
  if (!file) return;
  setStatus("正在处理图片…");
  const blob = await blobFromFile(file);
  usePhoto(blob, file.name);
}

fileUpload.addEventListener("change", onPickedFile);
fileCapture.addEventListener("change", onPickedFile);

analyzeButton.addEventListener("click", async () => {
  if (!photoBlob || !selectedModel) return;
  analyzeButton.disabled = true;
  setStatus("正在识别楼道隐患…");
  const form = new FormData();
  form.append("image", photoBlob, "capture.jpg");
  form.append("model", selectedModel);
  try {
    const response = await fetch("/api/analyze", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "识别失败");
    }
    showResult(data);
    setStatus("识别完成。");
  } catch (error) {
    setStatus(error.message || "识别失败", true);
  } finally {
    analyzeButton.disabled = !photoBlob;
  }
});

window.addEventListener("pagehide", stopCamera);
renderModels().catch(() => setStatus("页面初始化失败，请刷新。", true));
