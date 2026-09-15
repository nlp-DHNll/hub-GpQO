const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { runResearch } = require("./research");

const ROOT = __dirname;
const PORT = Number(process.env.PORT || 3000);

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon"
};

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => {
      data += chunk;
      if (data.length > 1e6) {
        reject(new Error("请求体过大"));
        req.destroy();
      }
    });
    req.on("end", () => {
      try {
        resolve(data ? JSON.parse(data) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload, null, 2);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body)
  });
  res.end(body);
}

function serveStatic(req, res) {
  const urlPath = req.url.split("?")[0];
  const safePath = urlPath === "/" ? "/index.html" : urlPath;
  const filePath = path.normalize(path.join(ROOT, safePath));

  if (!filePath.startsWith(ROOT)) {
    sendJson(res, 403, { error: "禁止访问" });
    return;
  }

  fs.readFile(filePath, (err, content) => {
    if (err) {
      res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      res.end("Not Found");
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, {
      "Content-Type": MIME[ext] || "application/octet-stream"
    });
    res.end(content);
  });
}

const server = http.createServer(async (req, res) => {
  if (req.method === "POST" && req.url.startsWith("/api/research")) {
    try {
      const body = await readBody(req);
      const topic = String(body.topic || "").trim();
      if (!topic) {
        sendJson(res, 400, { error: "请提供研究主题" });
        return;
      }
      const report = await runResearch(topic);
      sendJson(res, 200, report);
    } catch (error) {
      sendJson(res, 500, {
        error: "研究过程中发生错误",
        detail: error.message
      });
    }
    return;
  }

  if (req.method === "GET" && (req.url === "/api/health" || req.url === "/api/health/")) {
    sendJson(res, 200, { ok: true, name: "deep-research-assistant" });
    return;
  }

  if (req.method === "GET") {
    serveStatic(req, res);
    return;
  }

  sendJson(res, 405, { error: "方法不支持" });
});

server.listen(PORT, () => {
  console.log(`深度研究助手已启动：http://localhost:${PORT}`);
});
