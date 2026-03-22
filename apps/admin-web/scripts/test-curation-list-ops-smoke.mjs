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
const TAG_CREATE_DELAY_MS = Math.max(200, Number(process.env.TAG_CREATE_DELAY_MS || 1200));
const TEST_RESULTS_DIR = path.join(PROJECT_ROOT, "test-results");
const SCREENSHOT_PATH = path.join(TEST_RESULTS_DIR, "curation-list-ops-smoke.png");
const REPORT_PATH = path.join(TEST_RESULTS_DIR, "curation-list-ops-smoke.json");

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

function parseJsonBody(req) {
	return new Promise((resolve, reject) => {
		let raw = "";
		req.on("data", (chunk) => {
			raw += chunk;
		});
		req.on("end", () => {
			if (!raw) return resolve({});
			try {
				resolve(JSON.parse(raw));
			} catch (err) {
				reject(err);
			}
		});
		req.on("error", reject);
	});
}

function normalizeTagName(value) {
	return String(value || "").trim().toLowerCase();
}

function normalizeId(value) {
	return String(value || "").trim();
}

function buildTagsIndex(tags) {
	return {
		generated_at: new Date().toISOString(),
		tags_db_meta: {},
		tags: tags.map((tag) => ({
			id: String(tag.id),
			name: String(tag.name),
			aliases: Array.isArray(tag.aliases) ? tag.aliases.map(String) : [],
			status: String(tag.status || "active"),
			merge_to: String(tag.merge_to || ""),
			parents: Array.isArray(tag.parents) ? tag.parents.map(String) : [],
			children: Array.isArray(tag.children) ? tag.children.map(String) : [],
			usage_count: Number(tag.usage_count || 0),
		})),
	};
}

function clone(value) {
	return JSON.parse(JSON.stringify(value));
}

function createServerState() {
	return {
		tagSeq: 1,
		works: [
			{
				id: "work-1",
				title: "",
				completedDate: "2026-03-01",
				classroom: "A教室",
				authorIds: [],
				tagIds: [],
				caption: "",
				ready: false,
				notificationDisabled: false,
				notificationPending: false,
				notificationState: "sent",
				notificationReason: "",
				galleryReflected: false,
				images: [{ url: "https://example.com/work-1.jpg", name: "work-1.jpg", type: "external" }],
			},
			{
				id: "work-2",
				title: "作品2",
				completedDate: "2026-02-28",
				classroom: "B教室",
				authorIds: [],
				tagIds: [],
				caption: "",
				ready: true,
				notificationDisabled: false,
				notificationPending: false,
				notificationState: "sent",
				notificationReason: "",
				galleryReflected: true,
				images: [{ url: "https://example.com/work-2.jpg", name: "work-2.jpg", type: "external" }],
			},
			{
				id: "work-3",
				title: "作品3",
				completedDate: "2026-02-27",
				classroom: "A教室",
				authorIds: [],
				tagIds: [],
				caption: "",
				ready: false,
				notificationDisabled: false,
				notificationPending: false,
				notificationState: "queued",
				notificationReason: "",
				galleryReflected: false,
				images: [{ url: "https://example.com/work-3.jpg", name: "work-3.jpg", type: "external" }],
			},
		],
		tags: [
			{
				id: "tag-animal",
				name: "どうぶつ",
				aliases: ["アニマル"],
				status: "active",
				merge_to: "",
				parents: [],
				children: [],
				usage_count: 0,
			},
			{
				id: "tag-food",
				name: "たべもの",
				aliases: [],
				status: "active",
				merge_to: "",
				parents: [],
				children: [],
				usage_count: 0,
			},
		],
		tagCreateCallsByName: {},
		patchCalls: [],
		patchDelayMsByWorkId: {},
		mergeCalls: [],
		work2FailCount: 0,
		createdTagIdsByName: {},
	};
}

function startServer(state) {
	return new Promise((resolve, reject) => {
		const server = http.createServer(async (req, res) => {
			try {
				const method = String(req.method || "GET").toUpperCase();
				const url = new URL(String(req.url || "/"), `http://${HOST}`);
				const pathOnly = decodeURIComponent(url.pathname);

				if (pathOnly === "/admin/notion/schema" && method === "GET") {
					json(res, 200, {
						ok: true,
						classroomOptions: ["A教室", "B教室"],
						venueOptions: [],
						supportsAuthor: true,
						supportsVenue: false,
						tagInitialCandidateNames: ["どうぶつ", "たべもの"],
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
					json(res, 200, { ok: true, data: buildTagsIndex(state.tags) });
					return;
				}

				if (pathOnly === "/gallery.json" && method === "GET") {
					json(res, 200, { updated_at: new Date().toISOString(), works: [] });
					return;
				}

				if (pathOnly === "/admin/trigger-tags-index-update" && method === "POST") {
					json(res, 200, {
						ok: true,
						message: "tags index regenerated",
						key: "tags_index.json",
						count: state.tags.length,
						generated_at: new Date().toISOString(),
					});
					return;
				}

				if (pathOnly === "/admin/notion/works" && method === "GET") {
					const q = String(url.searchParams.get("q") || "").trim();
					let results = state.works.slice();
					if (q) {
						results = results.filter((work) => String(work.title || "").includes(q));
					}
					json(res, 200, {
						ok: true,
						results: clone(results),
						nextCursor: "",
					});
					return;
				}

				if (pathOnly === "/admin/curation/work-sync-status" && method === "POST") {
					const body = await parseJsonBody(req).catch(() => ({}));
					const workIds = Array.isArray(body.workIds) ? body.workIds.map(normalizeId).filter(Boolean) : [];
					const statuses = workIds.map((workId) => {
						const work = state.works.find((item) => item.id === workId) || null;
						return {
							workId,
							pending: false,
							galleryReflected: work ? Boolean(work.galleryReflected) : false,
							notification: {
								notificationDisabled: work ? Boolean(work.notificationDisabled) : false,
								notificationState: work ? String(work.notificationState || "") : "",
								rawState: work ? String(work.notificationState || "") : "",
								reason: work ? String(work.notificationReason || "") : "",
								updatedAt: new Date().toISOString(),
							},
						};
					});
					json(res, 200, {
						ok: true,
						statuses,
						pendingCount: 0,
						galleryLoaded: true,
						notificationStatusLoaded: true,
						notificationStatusReason: "",
						snapshotAt: new Date().toISOString(),
					});
					return;
				}

				if (pathOnly === "/admin/notion/tag" && method === "POST") {
					const body = await parseJsonBody(req);
					const name = String(body.name || "").trim();
					if (!name) {
						json(res, 400, { ok: false, error: "missing name" });
						return;
					}
					state.tagCreateCallsByName[name] = Number(state.tagCreateCallsByName[name] || 0) + 1;
					const nameKey = normalizeTagName(name);
					const existing = state.tags.find((tag) => {
						if (normalizeTagName(tag.name) === nameKey) return true;
						return (tag.aliases || []).some((alias) => normalizeTagName(alias) === nameKey);
					});
					if (existing) {
						json(res, 409, {
							ok: false,
							error: "duplicate",
							existing_id: existing.id,
							existing_tag: existing,
						});
						return;
					}
					await delay(TAG_CREATE_DELAY_MS);
					const id = `tag-new-${state.tagSeq++}`;
					const created = {
						id,
						name,
						aliases: [],
						status: "active",
						merge_to: "",
						parents: [],
						children: [],
						usage_count: 0,
					};
					state.tags.push(created);
					state.createdTagIdsByName[name] = id;
					json(res, 201, {
						ok: true,
						...created,
						tags_index_refresh_queued: true,
					});
					return;
				}

				if (pathOnly === "/admin/notion/tag" && method === "PATCH") {
					const body = await parseJsonBody(req).catch(() => ({}));
					const id = normalizeId(body.id);
					const tag = state.tags.find((item) => item.id === id);
					if (!tag) {
						json(res, 404, { ok: false, error: "tag not found" });
						return;
					}
					const addParentIds = Array.isArray(body.addParentIds) ? body.addParentIds.map(normalizeId).filter(Boolean) : [];
					const addChildIds = Array.isArray(body.addChildIds) ? body.addChildIds.map(normalizeId).filter(Boolean) : [];
					tag.parents = Array.from(new Set([...(tag.parents || []), ...addParentIds]));
					tag.children = Array.from(new Set([...(tag.children || []), ...addChildIds]));
					json(res, 200, { ok: true, ...clone(tag), tags_index_refresh_queued: true });
					return;
				}

				if (pathOnly === "/admin/notion/work" && method === "PATCH") {
					const body = await parseJsonBody(req).catch(() => ({}));
					const id = normalizeId(body.id);
					state.patchCalls.push(clone(body));
					const patchDelayMs = Number(state.patchDelayMsByWorkId[id] || 0);
					if (patchDelayMs > 0) {
						state.patchDelayMsByWorkId[id] = 0;
						await delay(patchDelayMs);
					}
					if (id === "work-2" && state.work2FailCount === 0) {
						state.work2FailCount += 1;
						json(res, 500, { ok: false, error: "forced failure for retry test" });
						return;
					}
					const idx = state.works.findIndex((work) => work.id === id);
					if (idx < 0) {
						json(res, 404, { ok: false, error: "work not found" });
						return;
					}
					state.works[idx] = {
						...state.works[idx],
						...(Object.prototype.hasOwnProperty.call(body, "title") ? { title: String(body.title || "").trim() } : {}),
						...(Object.prototype.hasOwnProperty.call(body, "completedDate")
							? { completedDate: String(body.completedDate || "").trim() }
							: {}),
						...(Object.prototype.hasOwnProperty.call(body, "classroom") ? { classroom: String(body.classroom || "").trim() } : {}),
						...(Object.prototype.hasOwnProperty.call(body, "authorIds")
							? {
									authorIds: Array.isArray(body.authorIds)
										? body.authorIds.map((value) => String(value || "").trim()).filter(Boolean)
										: [],
								}
							: {}),
						...(Object.prototype.hasOwnProperty.call(body, "caption") ? { caption: String(body.caption || "").trim() } : {}),
						...(Object.prototype.hasOwnProperty.call(body, "tagIds")
							? {
									tagIds: Array.isArray(body.tagIds)
										? body.tagIds.map((value) => String(value || "").trim()).filter(Boolean)
										: [],
								}
							: {}),
						...(Object.prototype.hasOwnProperty.call(body, "ready") ? { ready: Boolean(body.ready) } : {}),
						...(Object.prototype.hasOwnProperty.call(body, "notificationDisabled")
							? { notificationDisabled: Boolean(body.notificationDisabled) }
							: {}),
						...(Object.prototype.hasOwnProperty.call(body, "images")
							? { images: Array.isArray(body.images) ? clone(body.images) : [] }
							: {}),
					};
					json(res, 200, { ok: true, id });
					return;
				}

				if (pathOnly === "/admin/image/merge" && method === "POST") {
					const body = await parseJsonBody(req).catch(() => ({}));
					state.mergeCalls.push(clone(body));
					const targetWorkId = normalizeId(body.targetWorkId);
					const sourceWorkIds = Array.isArray(body.sourceWorkIds)
						? body.sourceWorkIds.map(normalizeId).filter((value) => value && value !== targetWorkId)
						: [];
					const targetIdx = state.works.findIndex((work) => work.id === targetWorkId);
					if (targetIdx < 0) {
						json(res, 404, { ok: false, error: "target not found" });
						return;
					}
					const target = state.works[targetIdx];
					const seen = new Set((target.images || []).map((img) => String(img.url || "").trim()).filter(Boolean));
					for (const sourceId of sourceWorkIds) {
						const source = state.works.find((work) => work.id === sourceId);
						if (!source) continue;
						for (const image of source.images || []) {
							const urlKey = String(image.url || "").trim();
							if (!urlKey || seen.has(urlKey)) continue;
							seen.add(urlKey);
							target.images.push(clone(image));
						}
					}
					state.works = state.works.filter((work) => !sourceWorkIds.includes(work.id));
					json(res, 200, {
						ok: true,
						mergedSources: sourceWorkIds.length,
						targetImageCount: target.images.length,
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

function buildResult({
	ok,
	saveNextOpenedNext,
	noImmediatePatchBeforeCommit,
	localDraftBadgeShown,
	firstSaveAvoidedStaleImages,
	editBlockedDuringCommit,
	missingWorkDraftRetained,
	backgroundSecondEditCaptured,
	saveFailureBadgeShown,
	saveRetryRecovered,
	tagCreateDeduped,
	firstSaveIncludesCreatedTag,
	readyBadgeShown,
	inlineTagSaveCaptured,
	mergeCallValid,
	pageErrors,
	consoleErrors,
	errorMessage = "",
}) {
	return {
		ok: Boolean(ok),
		saveNextOpenedNext: Boolean(saveNextOpenedNext),
		noImmediatePatchBeforeCommit: Boolean(noImmediatePatchBeforeCommit),
		localDraftBadgeShown: Boolean(localDraftBadgeShown),
		firstSaveAvoidedStaleImages: Boolean(firstSaveAvoidedStaleImages),
		editBlockedDuringCommit: Boolean(editBlockedDuringCommit),
		missingWorkDraftRetained: Boolean(missingWorkDraftRetained),
		backgroundSecondEditCaptured: Boolean(backgroundSecondEditCaptured),
		saveFailureBadgeShown: Boolean(saveFailureBadgeShown),
		saveRetryRecovered: Boolean(saveRetryRecovered),
		tagCreateDeduped: Boolean(tagCreateDeduped),
		firstSaveIncludesCreatedTag: Boolean(firstSaveIncludesCreatedTag),
		readyBadgeShown: Boolean(readyBadgeShown),
		inlineTagSaveCaptured: Boolean(inlineTagSaveCaptured),
		mergeCallValid: Boolean(mergeCallValid),
		pageErrors: Array.isArray(pageErrors) ? pageErrors : [],
		consoleErrors: Array.isArray(consoleErrors) ? consoleErrors : [],
		errorMessage: String(errorMessage || ""),
		screenshot: SCREENSHOT_PATH,
	};
}

async function runSmoke(port, state) {
	const browser = await chromium.launch({ headless: true });
	const page = await browser.newPage({ viewport: { width: 1360, height: 960 } });
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
		await page.goto(`http://${HOST}:${port}/admin.html`, { waitUntil: "domcontentloaded", timeout: 30000 });
		await page.click('.tab[data-tab="curation"]');
		await page.waitForFunction(() => document.querySelectorAll("#curation-grid .work-card").length >= 3, null, { timeout: 20000 });
		await page.waitForSelector("#view-curation.is-active #curation-grid .work-card", { state: "visible", timeout: 15000 });

		const readyBadgeShown = await page.evaluate(() => {
			const texts = Array.from(document.querySelectorAll("#curation-grid .chip"))
				.map((node) => String(node.textContent || "").trim())
				.filter(Boolean);
			return texts.some((text) => text.includes("整備: 済")) && texts.some((text) => text.includes("整備: 未"));
		});

		await page.locator("#curation-grid .work-card").first().click();
		const modal = page.locator("#modal-root .modal").first();
		await modal.waitFor({ state: "visible", timeout: 15000 });

		const tagInput = modal.locator(".tag-editor .tag-input input").first();
		await tagInput.fill("新規遅延タグ");
		const createSuggest = modal.locator(".tag-input .suggest .suggest-item").filter({ hasText: "新規作成" }).first();
		await createSuggest.waitFor({ state: "visible", timeout: 10000 });
		const firstClick = createSuggest.click();
		const secondClick = createSuggest.click();
		await Promise.allSettled([firstClick, secondClick]);

		await modal.getByRole("button", { name: "ローカル保存して次へ", exact: true }).click();
		await page.waitForFunction(() => {
			const title = document.querySelector("#modal-root .modal .modal-title");
			return Boolean(title && String(title.textContent || "").includes("work-2"));
		});
		const saveNextOpenedNext = await page.evaluate(() => {
			const title = document.querySelector("#modal-root .modal .modal-title");
			return Boolean(title && String(title.textContent || "").includes("work-2"));
		});
		const noImmediatePatchBeforeCommit = state.patchCalls.length === 0;

		await modal.locator("input.input[type=\"text\"]").first().fill("作品2更新");
		await modal.getByRole("button", { name: "ローカル保存", exact: true }).click();
		await page.waitForFunction(() => document.querySelector("#modal-root")?.getAttribute("aria-hidden") === "true");
		const localDraftBadgeShown = await page.evaluate(() =>
			Array.from(document.querySelectorAll("#curation-grid .chip")).some((node) =>
				String(node.textContent || "").includes("ローカル: 未反映"),
			),
		);
		state.works[0].images.push({
			url: "https://example.com/work-1-remote.jpg",
			name: "work-1-remote.jpg",
			type: "external",
		});
		state.patchDelayMsByWorkId["work-1"] = 700;

		await page.locator("#curation-grid .work-card .work-card__actions .btn").filter({ hasText: "タグ編集" }).first().click();
		await page.waitForSelector("#curation-inline-tag-panel:not([hidden])", { timeout: 10000 });
		const inlineTagInput = page.locator("#curation-inline-tag-editor .tag-editor .tag-input input").first();
		await inlineTagInput.fill("どう");
		const inlineSuggest = page.locator("#curation-inline-tag-editor .tag-input .suggest .suggest-item").filter({ hasText: "どうぶつ" }).first();
		await inlineSuggest.waitFor({ state: "visible", timeout: 10000 });
		await inlineSuggest.click();
		await page.click("#curation-inline-tag-save");
		await page.click("#curation-inline-tag-cancel");
		await page.waitForSelector("#curation-inline-tag-panel", { state: "hidden", timeout: 10000 });

		await page.click("#curation-commit-local");
		await page.waitForFunction(() => String(document.querySelector("#curation-local-status")?.textContent || "").includes("Notion反映中"));
		await page.locator("#curation-grid .work-card").nth(2).click();
		await delay(150);
		const editBlockedDuringCommit = await page.evaluate(
			() => document.querySelector("#modal-root")?.getAttribute("aria-hidden") === "true",
		);

		await page.waitForFunction(() =>
			Array.from(document.querySelectorAll("#curation-grid .chip")).some((node) =>
				String(node.textContent || "").includes("保存: 失敗"),
			),
		);
		const saveFailureBadgeShown = await page.evaluate(() =>
			Array.from(document.querySelectorAll("#curation-grid .chip")).some((node) =>
				String(node.textContent || "").includes("保存: 失敗"),
			),
		);

		await page.locator("#curation-grid .work-card .work-card__actions .btn").filter({ hasText: "保存を再試行" }).first().click();
		await page.waitForFunction(
			() =>
				!Array.from(document.querySelectorAll("#curation-grid .chip")).some((node) =>
					String(node.textContent || "").includes("保存: 失敗"),
				),
			null,
			{ timeout: 20000 },
		);
		const saveRetryRecovered = await page.evaluate(
			() =>
				!Array.from(document.querySelectorAll("#curation-grid .chip")).some((node) =>
					String(node.textContent || "").includes("保存: 失敗"),
				),
		);

		await page.locator("#curation-grid .work-card").nth(2).click();
		await modal.waitFor({ state: "visible", timeout: 15000 });
		await modal.locator("input.input[type=\"text\"]").first().fill("作品3ローカル");
		await modal.getByRole("button", { name: "ローカル保存", exact: true }).click();
		await page.waitForFunction(() => document.querySelector("#modal-root")?.getAttribute("aria-hidden") === "true");
		state.works = state.works.filter((work) => work.id !== "work-3");
		await page.click("#curation-refresh");
		await page.waitForFunction(() => {
			const status = String(document.querySelector("#curation-local-status")?.textContent || "");
			return status.includes("ローカル変更: 1件") && status.includes("一覧外: 1件");
		});
		const missingWorkDraftRetained = await page.evaluate(() => {
			const status = String(document.querySelector("#curation-local-status")?.textContent || "");
			return status.includes("ローカル変更: 1件") && status.includes("一覧外: 1件");
		});

		const cards = page.locator("#curation-grid .work-card");
		await cards.nth(0).locator(".work-card__actions .checkbox input").check();
		await cards.nth(1).locator(".work-card__actions .checkbox input").check();
		await cards.nth(0).locator(".work-card__actions .btn").filter({ hasText: "統合先" }).first().click();
		page.once("dialog", (dialog) => dialog.accept().catch(() => {}));
		await page.click("#curation-merge-run");
		await delay(800);

		await fs.mkdir(TEST_RESULTS_DIR, { recursive: true });
		await page.screenshot({ path: SCREENSHOT_PATH, fullPage: true });

		const createdTagId = state.createdTagIdsByName["新規遅延タグ"];
		const firstSavePatch = state.patchCalls.find((payload) => String(payload?.id || "") === "work-1");
		const firstSaveIncludesCreatedTag = Boolean(
			firstSavePatch &&
				Array.isArray(firstSavePatch.tagIds) &&
				createdTagId &&
				firstSavePatch.tagIds.map((value) => String(value || "")).includes(createdTagId),
		);
		const firstSaveAvoidedStaleImages = Boolean(
			firstSavePatch && !Object.prototype.hasOwnProperty.call(firstSavePatch, "images"),
		);
		const backgroundSecondEditCaptured = state.patchCalls.some(
			(payload) => String(payload?.id || "") === "work-2" && String(payload?.title || "") === "作品2更新",
		);
		const inlineTagSaveCaptured = state.patchCalls.some(
			(payload) => Array.isArray(payload?.tagIds) && payload.tagIds.map((value) => String(value || "")).includes("tag-animal"),
		);
		const tagCreateDeduped = Number(state.tagCreateCallsByName["新規遅延タグ"] || 0) === 1;
		const mergeCall = state.mergeCalls[0] || null;
		const mergeCallValid = Boolean(
			mergeCall &&
				String(mergeCall.targetWorkId || "").trim() &&
				Array.isArray(mergeCall.sourceWorkIds) &&
				mergeCall.sourceWorkIds.length >= 1 &&
				!mergeCall.sourceWorkIds.includes(mergeCall.targetWorkId),
		);

		const ok =
			saveNextOpenedNext &&
			noImmediatePatchBeforeCommit &&
			localDraftBadgeShown &&
			firstSaveAvoidedStaleImages &&
			editBlockedDuringCommit &&
			missingWorkDraftRetained &&
			backgroundSecondEditCaptured &&
			saveFailureBadgeShown &&
			saveRetryRecovered &&
			tagCreateDeduped &&
			firstSaveIncludesCreatedTag &&
			readyBadgeShown &&
			inlineTagSaveCaptured &&
			mergeCallValid &&
			pageErrors.length === 0;

		return buildResult({
			ok,
			saveNextOpenedNext,
			noImmediatePatchBeforeCommit,
			localDraftBadgeShown,
			firstSaveAvoidedStaleImages,
			editBlockedDuringCommit,
			missingWorkDraftRetained,
			backgroundSecondEditCaptured,
			saveFailureBadgeShown,
			saveRetryRecovered,
			tagCreateDeduped,
			firstSaveIncludesCreatedTag,
			readyBadgeShown,
			inlineTagSaveCaptured,
			mergeCallValid,
			pageErrors,
			consoleErrors,
			errorMessage: ok ? "" : "One or more assertions failed",
		});
	} finally {
		await browser.close();
	}
}

async function main() {
	let server = null;
	const state = createServerState();
	try {
		server = await startServer(state);
		const address = server.address();
		const port = typeof address === "object" && address ? address.port : REQUESTED_PORT;
		const result = await runSmoke(port, state);
		await fs.mkdir(TEST_RESULTS_DIR, { recursive: true });
		await fs.writeFile(REPORT_PATH, JSON.stringify(result, null, 2));
		console.log(JSON.stringify(result, null, 2));
		if (!result.ok) process.exitCode = 1;
	} catch (err) {
		const result = buildResult({
			ok: false,
			saveNextOpenedNext: false,
			noImmediatePatchBeforeCommit: false,
			localDraftBadgeShown: false,
			firstSaveAvoidedStaleImages: false,
			editBlockedDuringCommit: false,
			missingWorkDraftRetained: false,
			backgroundSecondEditCaptured: false,
			saveFailureBadgeShown: false,
			saveRetryRecovered: false,
			tagCreateDeduped: false,
			firstSaveIncludesCreatedTag: false,
			readyBadgeShown: false,
			inlineTagSaveCaptured: false,
			mergeCallValid: false,
			pageErrors: [],
			consoleErrors: [],
			errorMessage: String(err?.message || err),
		});
		await fs.mkdir(TEST_RESULTS_DIR, { recursive: true });
		await fs.writeFile(REPORT_PATH, JSON.stringify(result, null, 2));
		console.error(JSON.stringify(result, null, 2));
		process.exitCode = 1;
	} finally {
		await closeServer(server).catch(() => {});
	}
}

main();
