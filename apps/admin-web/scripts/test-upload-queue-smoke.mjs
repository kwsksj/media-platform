#!/usr/bin/env node

import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const __filename = fileURLToPath(import.meta.url);
const PROJECT_ROOT = path.resolve(path.dirname(__filename), "..");
const HOST = "127.0.0.1";
const REQUESTED_PORT = Number(process.env.SMOKE_PORT || 0);
const TEST_RESULTS_DIR = path.join(PROJECT_ROOT, "test-results");
const SCREENSHOT_PATH = path.join(TEST_RESULTS_DIR, "upload-queue-smoke.png");
const REPORT_PATH = path.join(TEST_RESULTS_DIR, "upload-queue-smoke.json");

const PNG_BASE64 = [
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7+P3kAAAAASUVORK5CYII=",
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAF/gL+5MzdWQAAAABJRU5ErkJggg==",
];

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

function startStaticServer() {
	return new Promise((resolve, reject) => {
		const server = http.createServer(async (req, res) => {
			try {
				const pathOnly = decodeURIComponent(String(req.url || "/").split("?")[0] || "/");
				if (pathOnly === "/gallery.json") {
					res.writeHead(200, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
					res.end(JSON.stringify({ updated_at: new Date().toISOString(), works: [] }));
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

				res.writeHead(200, { "Content-Type": contentTypeByPath(targetPath), "Cache-Control": "no-store" });
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

async function createFixtureImages() {
	const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "gallery-upload-smoke-"));
	const files = [];
	for (let i = 0; i < PNG_BASE64.length; i += 1) {
		const filePath = path.join(tempDir, `fixture-${i + 1}.png`);
		await fs.writeFile(filePath, Buffer.from(PNG_BASE64[i], "base64"));
		files.push(filePath);
	}
	return { tempDir, files };
}

function buildResult({
	ok,
	cardCount,
	statusText,
	selectionText,
	tagOrderOk,
	pageErrors,
	consoleErrors,
	errorMessage = "",
} = {}) {
	return {
		ok: Boolean(ok),
		cardCount: Number(cardCount || 0),
		statusText: String(statusText || ""),
		selectionText: String(selectionText || ""),
		tagOrderOk: Boolean(tagOrderOk),
		pageErrors: Array.isArray(pageErrors) ? pageErrors : [],
		consoleErrors: Array.isArray(consoleErrors) ? consoleErrors : [],
		errorMessage: String(errorMessage || ""),
		screenshot: SCREENSHOT_PATH,
	};
}

async function runSmoke(files, port) {
	const browser = await chromium.launch({ headless: true });
	const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
	const pageErrors = [];
	const consoleErrors = [];

	page.on("pageerror", (err) => pageErrors.push(String(err?.message || err)));
	page.on("console", (msg) => {
		if (msg.type() === "error") consoleErrors.push(msg.text());
	});

	try {
		await page.goto(`http://${HOST}:${port}/admin.html`, { waitUntil: "networkidle", timeout: 30000 });
		await page.waitForSelector("#upload-files", { state: "visible", timeout: 15000 });
		await page.setInputFiles("#upload-files", files);

		await page.waitForFunction(
			() => document.querySelectorAll("#upload-draft-list .upload-draft-card").length >= 2,
			{ timeout: 15000 },
		);

		const cardCount = await page.locator("#upload-draft-list .upload-draft-card").count();
		const statusText = await page.locator("#upload-draft-status").innerText();
		const selectionText = await page.locator("#upload-image-selection-status").innerText();
		const tagOrderOk = await page.evaluate(() => {
			const editor = document.querySelector("#upload-tag-editor");
			if (!editor) return false;
			const selectedChips = editor.querySelector(".chips");
			const tagInput = editor.querySelector(".tag-input");
			if (!selectedChips || !tagInput) return false;
			const relation = selectedChips.compareDocumentPosition(tagInput);
			return Boolean(relation & Node.DOCUMENT_POSITION_FOLLOWING);
		});

		await fs.mkdir(TEST_RESULTS_DIR, { recursive: true });
		await page.screenshot({ path: SCREENSHOT_PATH, fullPage: true });

		const syntaxLikeErrors = [...pageErrors, ...consoleErrors].filter((message) => /syntaxerror|unexpected token|already been declared/i.test(message));
		const ok = cardCount >= 2 && syntaxLikeErrors.length === 0 && tagOrderOk;
		return buildResult({
			ok,
			cardCount,
			statusText,
			selectionText,
			tagOrderOk,
			pageErrors,
			consoleErrors,
			errorMessage: ok ? "" : `Smoke failed: cards=${cardCount}, syntaxErrors=${syntaxLikeErrors.length}, tagOrderOk=${tagOrderOk}`,
		});
	} finally {
		await browser.close();
	}
}

async function main() {
	let server = null;
	let tempDir = "";
	try {
		const fixtures = await createFixtureImages();
		tempDir = fixtures.tempDir;
		server = await startStaticServer();
		const address = server.address();
		const port = typeof address === "object" && address ? address.port : REQUESTED_PORT;
		const result = await runSmoke(fixtures.files, port);
		await fs.mkdir(TEST_RESULTS_DIR, { recursive: true });
		await fs.writeFile(REPORT_PATH, JSON.stringify(result, null, 2));
		console.log(JSON.stringify(result, null, 2));
		if (!result.ok) process.exitCode = 1;
	} catch (err) {
		const result = buildResult({
			ok: false,
			errorMessage: String(err?.message || err),
		});
		await fs.mkdir(TEST_RESULTS_DIR, { recursive: true });
		await fs.writeFile(REPORT_PATH, JSON.stringify(result, null, 2));
		console.error(JSON.stringify(result, null, 2));
		process.exitCode = 1;
	} finally {
		await closeServer(server).catch(() => {});
		if (tempDir) await fs.rm(tempDir, { recursive: true, force: true }).catch(() => {});
	}
}

main();
