#!/usr/bin/env node

import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const __filename = fileURLToPath(import.meta.url);
const PROJECT_ROOT = path.resolve(path.dirname(__filename), "..");
const HOST = "127.0.0.1";
const REQUESTED_PORT = Number(process.env.SMOKE_PORT || 0);
const TRIGGER_DELAY_MS = Math.max(1000, Number(process.env.TRIGGER_DELAY_MS || 4000));
const TEST_RESULTS_DIR = path.join(PROJECT_ROOT, "test-results");
const REPORT_PATH = path.join(TEST_RESULTS_DIR, "tags-index-refresh-nonblocking.json");

const CONTENT_TYPES = new Map([
	[".html", "text/html; charset=utf-8"],
	[".js", "text/javascript; charset=utf-8"],
	[".css", "text/css; charset=utf-8"],
	[".json", "application/json; charset=utf-8"],
	[".png", "image/png"],
	[".jpg", "image/jpeg"],
	[".jpeg", "image/jpeg"],
	[".svg", "image/svg+xml"],
	[".ico", "image/x-icon"],
]);

function contentTypeByPath(filePath) {
	return CONTENT_TYPES.get(path.extname(filePath).toLowerCase()) || "application/octet-stream";
}

function resolveRequestToFile(urlPath) {
	const pathOnly = decodeURIComponent(String(urlPath || "/").split("?")[0] || "/");
	const normalized = pathOnly === "/" ? "/admin.html" : pathOnly;
	const candidate = path.resolve(PROJECT_ROOT, `.${normalized}`);
	if (candidate !== PROJECT_ROOT && !candidate.startsWith(`${PROJECT_ROOT}${path.sep}`)) return null;
	return candidate;
}

function delay(ms) {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

function json(res, status, body) {
	res.writeHead(status, {
		"Content-Type": "application/json; charset=utf-8",
		"Cache-Control": "no-store",
	});
	res.end(JSON.stringify(body));
}

function startStaticServer(state) {
	return new Promise((resolve, reject) => {
		const server = http.createServer(async (req, res) => {
			try {
				const method = String(req.method || "GET").toUpperCase();
				const pathOnly = decodeURIComponent(String(req.url || "/").split("?")[0] || "/");

				if (pathOnly === "/admin/trigger-tags-index-update" && method === "POST") {
					state.triggerRequestCount += 1;
					if (!state.triggerStartedAtMs) state.triggerStartedAtMs = Date.now();
					await delay(TRIGGER_DELAY_MS);
					state.triggerFinishedAtMs = Date.now();
					json(res, 200, {
						ok: true,
						message: "tags index regenerated",
						key: "tags_index.json",
						count: 0,
						generated_at: new Date().toISOString(),
					});
					return;
				}

				if (pathOnly === "/admin/notion/schema" && method === "GET") {
					json(res, 200, {
						ok: true,
						classroomOptions: [],
						createdAtOptions: [],
						statusOptions: [],
					});
					return;
				}

				if (pathOnly === "/admin/notion/works" && method === "GET") {
					json(res, 200, {
						ok: true,
						results: [],
						nextCursor: "",
					});
					return;
				}

				if (pathOnly === "/admin/curation/work-sync-status" && method === "POST") {
					json(res, 200, {
						ok: true,
						statuses: [],
						pendingCount: 0,
						galleryLoaded: true,
						notificationStatusLoaded: true,
						notificationStatusReason: "",
						snapshotAt: new Date().toISOString(),
					});
					return;
				}

				if (pathOnly === "/participants-index" && method === "GET") {
					json(res, 200, { ok: true, data: { dates: {} } });
					return;
				}

				if (pathOnly === "/students-index" && method === "GET") {
					json(res, 200, { ok: true, data: { students: [] } });
					return;
				}

				if (pathOnly === "/tags-index" && method === "GET") {
					json(res, 200, {
						ok: true,
						data: {
							generated_at: new Date().toISOString(),
							tags: [],
						},
					});
					return;
				}

				if (pathOnly === "/gallery.json" && method === "GET") {
					json(res, 200, {
						updated_at: new Date().toISOString(),
						works: [],
					});
					return;
				}

				const filePath = resolveRequestToFile(req.url);
				if (!filePath) {
					res.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
					res.end("Forbidden");
					return;
				}

				const stat = await fs.stat(filePath).catch(() => null);
				const targetPath = stat?.isDirectory() ? path.join(filePath, "index.html") : filePath;
				const body = await fs.readFile(targetPath).catch(() => null);
				if (!body) {
					res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
					res.end("File not found");
					return;
				}

				res.writeHead(200, {
					"Content-Type": contentTypeByPath(targetPath),
					"Cache-Control": "no-store",
				});
				res.end(body);
			} catch (err) {
				res.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
				res.end(`Internal error: ${err?.message || "unknown"}`);
			}
		});

		server.once("error", reject);
		server.listen(REQUESTED_PORT, HOST, () => resolve(server));
	});
}

function closeServer(server) {
	if (!server) return Promise.resolve();
	return new Promise((resolve, reject) => {
		server.close((err) => {
			if (err) reject(err);
			else resolve();
		});
	});
}

async function runSmoke(port, serverState) {
	const browser = await chromium.launch({ headless: true });
	const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
	const pageErrors = [];
	const consoleErrors = [];

	page.on("pageerror", (err) => pageErrors.push(String(err?.message || err)));
	page.on("console", (msg) => {
		if (msg.type() === "error") consoleErrors.push(msg.text());
	});

	try {
		await page.addInitScript(() => {
			window.ADMIN_API_BASE = window.location.origin;
			window.ADMIN_API_TOKEN = "smoke-token";
			window.localStorage.setItem("gallery.adminApiToken.v1", "smoke-token");
		});

		const startedAtMs = Date.now();
		await page.goto(`http://${HOST}:${port}/admin.html`, { waitUntil: "domcontentloaded", timeout: 30000 });
		await page.waitForSelector("#upload-tag-editor .tag-editor", { state: "attached", timeout: 15000 });
		const uiReadyAtMs = Date.now();

		let triggerFinishedAtMs = serverState.triggerFinishedAtMs;
		if (!triggerFinishedAtMs && serverState.triggerRequestCount > 0) {
			const waitUntil = Date.now() + TRIGGER_DELAY_MS + 3000;
			while (!serverState.triggerFinishedAtMs && Date.now() < waitUntil) {
				await delay(50);
			}
			triggerFinishedAtMs = serverState.triggerFinishedAtMs || 0;
		}

		const elapsedToUiReadyMs = uiReadyAtMs - startedAtMs;
		const triggerRequestSeen = serverState.triggerRequestCount > 0;
		const uiReadyBeforeTriggerCompletion = triggerFinishedAtMs ? uiReadyAtMs < triggerFinishedAtMs : triggerRequestSeen;

		const ok = triggerRequestSeen && uiReadyBeforeTriggerCompletion && pageErrors.length === 0;
		return {
			ok,
			triggerDelayMs: TRIGGER_DELAY_MS,
			elapsedToUiReadyMs,
			triggerRequestCount: serverState.triggerRequestCount,
			triggerStartedAtMs: serverState.triggerStartedAtMs,
			triggerFinishedAtMs: serverState.triggerFinishedAtMs,
			uiReadyAtMs,
			uiReadyBeforeTriggerCompletion,
			pageErrors,
			consoleErrors,
			errorMessage: ok
				? ""
				: `triggerRequestSeen=${triggerRequestSeen}, uiReadyBeforeTriggerCompletion=${uiReadyBeforeTriggerCompletion}, pageErrors=${pageErrors.length}`,
		};
	} finally {
		await browser.close();
	}
}

async function main() {
	let server = null;
	const serverState = {
		triggerRequestCount: 0,
		triggerStartedAtMs: 0,
		triggerFinishedAtMs: 0,
	};

	try {
		server = await startStaticServer(serverState);
		const address = server.address();
		const port = typeof address === "object" && address ? address.port : REQUESTED_PORT;
		const result = await runSmoke(port, serverState);

		await fs.mkdir(TEST_RESULTS_DIR, { recursive: true });
		await fs.writeFile(REPORT_PATH, JSON.stringify(result, null, 2));
		console.log(JSON.stringify(result, null, 2));
		if (!result.ok) process.exitCode = 1;
	} catch (err) {
		const result = {
			ok: false,
			errorMessage: String(err?.message || err),
			triggerDelayMs: TRIGGER_DELAY_MS,
		};
		await fs.mkdir(TEST_RESULTS_DIR, { recursive: true });
		await fs.writeFile(REPORT_PATH, JSON.stringify(result, null, 2));
		console.error(JSON.stringify(result, null, 2));
		process.exitCode = 1;
	} finally {
		await closeServer(server).catch(() => {});
	}
}

main();
