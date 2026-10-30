(function () {
  "use strict";

  var $ = function (s) { return document.querySelector(s); };

  var state = {
    provider: "deepseek",
    imageDataUrl: null,
    stream: null,
    history: []
  };

  var LEVELS = {
    high:         { color: "#ff4757", title: "高风险" },
    medium:       { color: "#ff9f43", title: "中风险" },
    low:          { color: "#fbc531", title: "低风险" },
    none:         { color: "#2ed573", title: "无风险" },
    non_stairwell:{ color: "#a4b0be", title: "非楼道" }
  };

  /* ---------------- 工具 ---------------- */
  function toast(msg) {
    var t = $("#toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(t._timer);
    t._timer = setTimeout(function () { t.classList.remove("show"); }, 2600);
  }

  function showLoading(on) { $("#loading").hidden = !on; }

  /* ---------------- 模型选择 ---------------- */
  document.querySelectorAll("#modelSeg button").forEach(function (b) {
    b.addEventListener("click", function () {
      document.querySelectorAll("#modelSeg button").forEach(function (x) {
        x.classList.remove("active");
      });
      b.classList.add("active");
      state.provider = b.dataset.provider;
    });
  });

  /* ---------------- 密钥状态 ---------------- */
  fetch("/api/health").then(function (r) { return r.json(); }).then(function (h) {
    if (!h.ok) return;
    var parts = [];
    Object.keys(h.keys || {}).forEach(function (k) {
      var v = h.keys[k];
      parts.push(v.label + "：" + (v.configured ? "已配置" : "未配置"));
    });
    $("#keyStatus").textContent = "密钥：" + parts.join(" · ");
  }).catch(function () { $("#keyStatus").textContent = "密钥：无法检测（请确认服务已启动）"; });

  /* ---------------- 图片压缩 ---------------- */
  function compressDataUrl(dataUrl, maxEdge, quality) {
    maxEdge = maxEdge || 1568; quality = quality == null ? 0.85 : quality;
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        var scale = Math.min(1, maxEdge / Math.max(img.width, img.height));
        var c = document.createElement("canvas");
        c.width = Math.max(1, Math.round(img.width * scale));
        c.height = Math.max(1, Math.round(img.height * scale));
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        try { resolve(c.toDataURL("image/jpeg", quality)); }
        catch (e) { reject(e); }
      };
      img.onerror = function () { reject(new Error("图片解析失败")); };
      img.src = dataUrl;
    });
  }

  function fileToDataUrl(file) {
    return new Promise(function (resolve, reject) {
      var r = new FileReader();
      r.onload = function () { resolve(r.result); };
      r.onerror = function () { reject(new Error("读取文件失败")); };
      r.readAsDataURL(file);
    });
  }

  function useFile(file) {
    if (!file || !/^image\//.test(file.type)) { toast("请选择图片文件"); return; }
    if (file.size > 20 * 1024 * 1024) { toast("图片超过 20MB，请压缩后重试"); return; }
    fileToDataUrl(file).then(function (dataUrl) {
      return compressDataUrl(dataUrl).then(function (small) {
        state.imageDataUrl = small;
        showPreview(small);
        analyze();
      });
    }).catch(function (e) { toast(e.message || "图片处理失败"); });
  }

  /* ---------------- 拍照（getUserMedia + 系统相机兜底） ---------------- */
  function openCamera() {
    var secure = window.isSecureContext;
    var hasMedia = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    if (secure && hasMedia) {
      navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } })
        .then(function (stream) {
          state.stream = stream;
          var v = $("#cameraVideo");
          v.srcObject = stream;
          $("#cameraOverlay").hidden = false;
          v.play().catch(function () {});
        })
        .catch(function () { $("#fileCamera").click(); });
    } else {
      // 非安全上下文（如局域网 http://IP）下 getUserMedia 不可用，调用系统相机
      $("#fileCamera").click();
    }
  }

  function stopStream() {
    if (state.stream) {
      state.stream.getTracks().forEach(function (t) { t.stop(); });
      state.stream = null;
    }
    $("#cameraVideo").srcObject = null;
  }

  function snap() {
    var v = $("#cameraVideo");
    if (!v.videoWidth) { toast("相机未就绪，请重试"); return; }
    var c = document.createElement("canvas");
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext("2d").drawImage(v, 0, 0);
    $("#cameraOverlay").hidden = true;
    stopStream();
    var dataUrl = c.toDataURL("image/jpeg", 0.9);
    compressDataUrl(dataUrl).then(function (small) {
      state.imageDataUrl = small;
      showPreview(small);
      analyze();
    }).catch(function (e) { toast(e.message || "拍照处理失败"); });
  }

  $("#btnCamera").addEventListener("click", openCamera);
  $("#btnShoot").addEventListener("click", snap);
  $("#btnCloseCamera").addEventListener("click", function () {
    $("#cameraOverlay").hidden = true;
    stopStream();
  });
  $("#fileCamera").addEventListener("change", function (e) {
    if (e.target.files && e.target.files[0]) useFile(e.target.files[0]);
    e.target.value = "";
  });

  /* ---------------- 上传 ---------------- */
  $("#btnUpload").addEventListener("click", function () { $("#fileUpload").click(); });
  $("#fileUpload").addEventListener("change", function (e) {
    if (e.target.files && e.target.files[0]) useFile(e.target.files[0]);
    e.target.value = "";
  });

  /* ---------------- 预览与清除 ---------------- */
  function showPreview(dataUrl) {
    $("#previewImg").src = dataUrl;
    $("#previewBox").hidden = false;
  }

  $("#btnClear").addEventListener("click", function () {
    state.imageDataUrl = null;
    $("#previewBox").hidden = true;
    $("#resultBox").hidden = true;
  });

  /* ---------------- 识别 ---------------- */
  function analyze() {
    if (!state.imageDataUrl) return;
    showLoading(true);
    var payload = { provider: state.provider, image: state.imageDataUrl };
    fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json(); }).then(function (data) {
      if (!data.ok) { toast(data.error || "识别失败，请重试"); return; }
      renderResult(data);
      pushHistory(data);
    }).catch(function (e) {
      toast("网络错误：" + e.message);
    }).finally(function () {
      showLoading(false);
    });
  }

  function renderResult(data) {
    var lv = LEVELS[data.level] || LEVELS.non_stairwell;
    var box = $("#resultBox");
    box.hidden = false;
    box.style.borderLeftColor = lv.color;
    $("#resultBadge").style.background = lv.color;
    $("#resultTitle").textContent = lv.title;
    $("#resultTag").textContent = data.level || data.category;
    $("#resultReason").textContent = data.reason || "（模型未给出判断依据）";
    $("#resultMeta").textContent =
      "模型：" + (data.model || "-") + " · 耗时：" + (data.latency_ms != null ? data.latency_ms + " ms" : "-") +
      " · 图片：" + (data.image_bytes != null ? Math.round(data.image_bytes / 1024) + " KB" : "-");
  }

  /* ---------------- 会话记录 ---------------- */
  function pushHistory(data) {
    state.history.unshift({
      category: data.category,
      level: data.level,
      reason: data.reason,
      thumb: state.imageDataUrl,
      time: new Date()
    });
    if (state.history.length > 8) state.history.pop();
    renderHistory();
  }

  function renderHistory() {
    var box = $("#historyBox");
    if (!state.history.length) { box.hidden = true; return; }
    box.hidden = false;
    var ul = $("#historyList");
    ul.innerHTML = "";
    state.history.forEach(function (h) {
      var lv = LEVELS[h.level] || LEVELS.non_stairwell;
      var li = document.createElement("li");
      li.innerHTML =
        '<img class="hist-thumb" src="' + h.thumb + '" alt="">' +
        '<span class="hist-dot" style="background:' + lv.color + '"></span>' +
        '<span class="hist-info"><span class="hist-cat">' + h.category +
        '</span><div class="hist-time">' + h.time.toLocaleTimeString("zh-CN", { hour12: false }) + " · " + h.reason + "</div></span>";
      ul.appendChild(li);
    });
  }
})();
