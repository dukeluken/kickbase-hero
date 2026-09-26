"use strict";

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const HOST = "127.0.0.1";
const PORT = Number(process.env.PORT || 3000);
const BASE_URL = "https://api.kickbase.com/v4";
const INDEX_PATH = path.join(__dirname, "index.html");
let kickbaseToken = null;

function sendJson(response, status, data) {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(JSON.stringify(data));
}

function readJson(request) {
  return new Promise((resolve, reject) => {
    let body = "";
    request.on("data", (chunk) => {
      body += chunk;
      if (body.length > 1_000_000) {
        reject(new Error("Anfrage ist zu groß."));
        request.destroy();
      }
    });
    request.on("end", () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        reject(new Error("Ungültiges JSON in der Anfrage."));
      }
    });
    request.on("error", reject);
  });
}

async function kickbaseRequest(endpoint, options = {}) {
  if (!kickbaseToken) {
    const error = new Error("Bitte zuerst bei Kickbase anmelden.");
    error.status = 401;
    throw error;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12_000);
  try {
    const response = await fetch(`${BASE_URL}${endpoint}`, {
      ...options,
      signal: controller.signal,
      headers: {
        Authorization: `Bearer ${kickbaseToken}`,
        Accept: "application/json",
        ...options.headers,
      },
    });
    const text = await response.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      throw new Error("Kickbase hat eine ungültige Antwort zurückgegeben.");
    }
    if (!response.ok) {
      const error = new Error(data.message || `Kickbase-Fehler (${response.status}).`);
      error.status = response.status === 401 ? 401 : 502;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError") {
      const timeoutError = new Error("Kickbase antwortet gerade nicht. Bitte erneut versuchen.");
      timeoutError.status = 504;
      throw timeoutError;
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function cleanText(value) {
  return typeof value === "string" ? value.replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").trim() : "";
}

async function getNews() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    const response = await fetch("https://www.ligainsider.de/rss/", {
      headers: { "User-Agent": "KickbaseHero/1.0 (local RSS reader)" },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("LigaInsider-News konnten nicht geladen werden.");
    const xml = await response.text();
    const items = [...xml.matchAll(/<item\b[^>]*>([\s\S]*?)<\/item>/gi)].map((match) => {
      const field = (tag) => {
        const found = match[1].match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>`, "i"));
        return found ? cleanText(found[1].replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")) : "";
      };
      return { title: field("title"), link: field("link"), summary: field("description"), published: field("pubDate") };
    });
    return items.filter((item) => item.title && item.link).slice(0, 40);
  } finally {
    clearTimeout(timeout);
  }
}

function matchNews(news, players) {
  const positive = ["startelf", "fit", "trainingsrückkehr", "kader", "einsatzbereit", "startet", "mit dabei", "beschwerdefrei"];
  const negative = ["ausfall", "verletz", "fehlt", "gesperrt", "fraglich", "abbruch", "pause", "geschont", "ausgewechselt", "operiert"];
  const alerts = [];
  for (const player of players) {
    const first = String(player.firstName || "").trim();
    const last = String(player.lastName || "").trim();
    if (!last) continue;
    const fullName = `${first} ${last}`.trim();
    const fullPattern = new RegExp(`\\b${escapeRegex(fullName)}\\b`, "i");
    const lastPattern = last.length > 3 ? new RegExp(`\\b${escapeRegex(last)}\\b`, "i") : null;
    const entry = news.find((item) => fullPattern.test(`${item.title} ${item.summary}`) || (lastPattern && lastPattern.test(`${item.title} ${item.summary}`)));
    if (!entry) continue;
    const text = `${entry.title} ${entry.summary}`.toLocaleLowerCase("de-DE");
    const isNegative = negative.some((word) => text.includes(word));
    const isPositive = positive.some((word) => text.includes(word));
    alerts.push({
      playerName: fullName,
      signal: isNegative ? "NEGATIV" : isPositive ? "POSITIV" : "NEUTRAL",
      title: entry.title,
      link: entry.link,
      published: entry.published,
    });
  }
  return alerts;
}

async function handleApi(request, response, url) {
  if (request.method === "POST" && url.pathname === "/api/login") {
    const { email, password } = await readJson(request);
    if (typeof email !== "string" || typeof password !== "string" || !email.trim() || !password) {
      return sendJson(response, 400, { error: "Bitte E-Mail und Passwort eingeben." });
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12_000);
    try {
      const result = await fetch(`${BASE_URL}/user/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ em: email.trim(), pass: password, loy: false, rep: {} }),
        signal: controller.signal,
      });
      const data = await result.json().catch(() => ({}));
      if (!result.ok || !data.tkn) {
        kickbaseToken = null;
        return sendJson(response, 401, { error: "Login fehlgeschlagen. Bitte Zugangsdaten prüfen." });
      }
      kickbaseToken = data.tkn;
      return sendJson(response, 200, { success: true });
    } catch (error) {
      const message = error.name === "AbortError" ? "Zeitüberschreitung beim Kickbase-Login." : "Kickbase ist gerade nicht erreichbar.";
      return sendJson(response, 502, { error: message });
    } finally {
      clearTimeout(timeout);
    }
  }

  if (request.method === "POST" && url.pathname === "/api/logout") {
    kickbaseToken = null;
    return sendJson(response, 200, { success: true });
  }

  if (request.method !== "GET") return sendJson(response, 405, { error: "Methode nicht erlaubt." });
  if (url.pathname === "/api/leagues") {
    const data = await kickbaseRequest("/leagues/selection");
    return sendJson(response, 200, { leagues: Array.isArray(data.leagues) ? data.leagues : [] });
  }
  if (url.pathname === "/api/news") {
    const news = await getNews();
    return sendJson(response, 200, { news });
  }

  const playersMatch = url.pathname.match(/^\/api\/leagues\/([^/]+)\/(market|lineup)$/);
  if (playersMatch) {
    const [, leagueId, type] = playersMatch;
    const data = await kickbaseRequest(`/leagues/${encodeURIComponent(leagueId)}/${type}`);
    const players = Array.isArray(data.players) ? data.players : [];
    let alerts = [];
    if (type === "market" && players.length) {
      try {
        alerts = matchNews(await getNews(), players);
      } catch {
        alerts = [];
      }
    }
    return sendJson(response, 200, { players, alerts });
  }

  const statsMatch = url.pathname.match(/^\/api\/players\/([^/]+)\/stats$/);
  if (statsMatch) {
    const data = await kickbaseRequest(`/players/${encodeURIComponent(statsMatch[1])}/stats`);
    return sendJson(response, 200, data);
  }
  return sendJson(response, 404, { error: "API-Endpunkt nicht gefunden." });
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, `http://${HOST}:${PORT}`);
  if (url.pathname.startsWith("/api/")) {
    try {
      await handleApi(request, response, url);
    } catch (error) {
      sendJson(response, error.status || 502, { error: error.message || "Unerwarteter Fehler." });
    }
    return;
  }
  if (request.method !== "GET" || !["/", "/index.html"].includes(url.pathname)) {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Nicht gefunden");
    return;
  }
  fs.readFile(INDEX_PATH, (error, content) => {
    if (error) {
      response.writeHead(500);
      return response.end("index.html konnte nicht geladen werden.");
    }
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "X-Content-Type-Options": "nosniff" });
    response.end(content);
  });
});

server.listen(PORT, HOST, () => {
  console.log(`Kickbase Hero läuft lokal auf http://${HOST}:${PORT}`);
});
