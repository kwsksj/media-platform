#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const NOTION_API_BASE = "https://api.notion.com/v1";
const NOTION_VERSION = "2022-06-28";
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const MONOREPO_ROOT = path.resolve(SCRIPT_DIR, "..", "..", "..");

function parseArgs(argv) {
	const args = {
		envFile: "",
		outDir: "",
	};
	for (let i = 0; i < argv.length; i += 1) {
		const value = argv[i];
		if (value === "--env-file") {
			args.envFile = argv[i + 1] || "";
			i += 1;
			continue;
		}
		if (value === "--out-dir") {
			args.outDir = argv[i + 1] || "";
			i += 1;
			continue;
		}
		if (value === "-h" || value === "--help") {
			printHelp();
			process.exit(0);
		}
		throw new Error(`Unknown option: ${value}`);
	}
	return args;
}

function printHelp() {
	console.log(`Build students_index.json and tags_index.json from Notion.

Usage:
  node scripts/build-admin-indexes.mjs [--env-file /path/to/media-platform/.env] [--out-dir /tmp/admin-indexes]

Environment variables (required):
  NOTION_TOKEN
  NOTION_WORKS_DB_ID (or NOTION_DATABASE_ID)
  NOTION_TAGS_DB_ID (or TAGS_DATABASE_ID)

Environment variables (optional):
  NOTION_STUDENTS_DB_ID
  NOTION_WORKS_AUTHOR_PROP
  NOTION_STUDENTS_ID_PROP
  NOTION_STUDENTS_TITLE_PROP
  NOTION_TAGS_TITLE_PROP
  NOTION_TAGS_STATUS_PROP
  NOTION_TAGS_ALIASES_PROP
  NOTION_TAGS_MERGE_TO_PROP
  NOTION_TAGS_PARENTS_PROP
  NOTION_TAGS_CHILDREN_PROP
  NOTION_TAGS_USAGE_COUNT_PROP
`);
}

function parseEnvLine(line) {
	const trimmed = line.trim();
	if (!trimmed || trimmed.startsWith("#")) return null;
	const idx = trimmed.indexOf("=");
	if (idx <= 0) return null;
	const key = trimmed.slice(0, idx).trim();
	let raw = trimmed.slice(idx + 1).trim();
	if (!key) return null;
	if (
		(raw.startsWith('"') && raw.endsWith('"')) ||
		(raw.startsWith("'") && raw.endsWith("'"))
	) {
		raw = raw.slice(1, -1);
	}
	return { key, value: raw };
}

async function loadEnvFile(filePath) {
	if (!filePath) return;
	const content = await fs.readFile(filePath, "utf8");
	for (const line of content.split(/\r?\n/u)) {
		const kv = parseEnvLine(line);
		if (!kv) continue;
		if (process.env[kv.key] === undefined) process.env[kv.key] = kv.value;
	}
}

function env(key, fallback = "") {
	return String(process.env[key] || fallback).trim();
}

function asString(value) {
	return typeof value === "string" ? value : "";
}

function notionHeaders(token) {
	return {
		Authorization: `Bearer ${token}`,
		"Notion-Version": NOTION_VERSION,
		"Content-Type": "application/json",
	};
}

async function notionRequest(token, method, apiPath, body) {
	const res = await fetch(`${NOTION_API_BASE}${apiPath}`, {
		method,
		headers: notionHeaders(token),
		body: body ? JSON.stringify(body) : undefined,
	});

	const contentType = res.headers.get("content-type") || "";
	const isJson = contentType.includes("application/json");
	const data = isJson ? await res.json().catch(() => null) : await res.text().catch(() => null);

	if (!res.ok) {
		const detail = typeof data === "string" ? data : JSON.stringify(data);
		throw new Error(`Notion API ${method} ${apiPath} failed (${res.status}): ${detail}`);
	}

	return data;
}

async function queryAllPages(token, databaseId, queryBody = {}) {
	const pages = [];
	let cursor = "";

	while (true) {
		const body = { page_size: 100, ...queryBody };
		if (cursor) body.start_cursor = cursor;
		const data = await notionRequest(token, "POST", `/databases/${databaseId}/query`, body);
		const results = Array.isArray(data?.results) ? data.results : [];
		pages.push(...results);
		if (!data?.has_more) break;
		cursor = asString(data?.next_cursor);
		if (!cursor) break;
	}

	return pages;
}

async function notionSearchDatabases(token) {
	const all = [];
	let cursor = "";
	while (true) {
		const body = {
			page_size: 100,
			filter: { property: "object", value: "database" },
		};
		if (cursor) body.start_cursor = cursor;
		const data = await notionRequest(token, "POST", "/search", body);
		const rows = Array.isArray(data?.results) ? data.results : [];
		all.push(...rows);
		if (!data?.has_more) break;
		cursor = asString(data?.next_cursor);
		if (!cursor) break;
	}
	return all;
}

function databaseProps(database) {
	return database?.properties || {};
}

function findFirstPropertyNameByType(database, type) {
	const props = databaseProps(database);
	for (const [name, prop] of Object.entries(props)) {
		if (prop?.type === type) return name;
	}
	return "";
}

function pickPropertyName(database, preferredNames, fallbackType = "") {
	const props = databaseProps(database);
	for (const name of preferredNames) {
		if (name && props[name]) return name;
	}
	if (fallbackType) return findFirstPropertyNameByType(database, fallbackType);
	return "";
}

function extractPlainTextItems(items) {
	if (!Array.isArray(items)) return "";
	return items.map((item) => asString(item?.plain_text)).join("").trim();
}

function extractPropertyText(prop) {
	if (!prop || typeof prop !== "object") return "";
	const type = prop.type;
	if (type === "title") return extractPlainTextItems(prop.title);
	if (type === "rich_text") return extractPlainTextItems(prop.rich_text);
	if (type === "select") return asString(prop.select?.name).trim();
	if (type === "status") return asString(prop.status?.name).trim();
	if (type === "email") return asString(prop.email).trim();
	if (type === "phone_number") return asString(prop.phone_number).trim();
	if (type === "url") return asString(prop.url).trim();
	if (type === "number") return Number.isFinite(prop.number) ? String(prop.number) : "";
	if (type === "formula") {
		const f = prop.formula;
		if (!f) return "";
		if (f.type === "string") return asString(f.string).trim();
		if (f.type === "number") return Number.isFinite(f.number) ? String(f.number) : "";
		if (f.type === "boolean") return f.boolean ? "true" : "false";
		return "";
	}
	if (type === "rollup") {
		const r = prop.rollup;
		if (!r) return "";
		if (r.type === "number") return Number.isFinite(r.number) ? String(r.number) : "";
		if (r.type === "array") return String(Array.isArray(r.array) ? r.array.length : 0);
		return "";
	}
	return "";
}

function extractPropertyNumber(prop) {
	if (!prop || typeof prop !== "object") return 0;
	const type = prop.type;
	if (type === "number") return Number.isFinite(prop.number) ? prop.number : 0;
	if (type === "formula") {
		const f = prop.formula;
		if (!f) return 0;
		if (f.type === "number" && Number.isFinite(f.number)) return f.number;
		if (f.type === "string") {
			const parsed = Number(f.string);
			return Number.isFinite(parsed) ? parsed : 0;
		}
		return 0;
	}
	if (type === "rollup") {
		const r = prop.rollup;
		if (!r) return 0;
		if (r.type === "number" && Number.isFinite(r.number)) return r.number;
		if (r.type === "array") return Array.isArray(r.array) ? r.array.length : 0;
		return 0;
	}
	const parsed = Number(extractPropertyText(prop));
	return Number.isFinite(parsed) ? parsed : 0;
}

function extractRelationIds(prop) {
	const relation = prop?.relation;
	if (!Array.isArray(relation)) return [];
	return relation.map((item) => asString(item?.id)).filter(Boolean);
}

function splitAliases(text) {
	if (!text) return [];
	return text
		.split(/[\s,、，;；\n\r\t]+/u)
		.map((value) => value.trim())
		.filter(Boolean);
}

function extractAliases(prop) {
	if (!prop || typeof prop !== "object") return [];
	if (prop.type === "multi_select") {
		return (prop.multi_select || [])
			.map((opt) => asString(opt?.name).trim())
			.filter(Boolean);
	}
	return splitAliases(extractPropertyText(prop));
}

function normalizeStatus(raw) {
	const value = asString(raw).trim().toLowerCase();
	if (!value) return "active";
	if (value.includes("merged") || value.includes("統合")) return "merged";
	if (value.includes("hidden") || value.includes("非表示")) return "hidden";
	return "active";
}

function splitStudentNameLabel(value) {
	const raw = asString(value).trim();
	if (!raw) return { nickname: "", realName: "" };
	const match = raw.match(/^(.+?)\s*[|｜]\s*(.+)$/u);
	if (!match) return { nickname: raw, realName: "" };
	return { nickname: asString(match[1]).trim(), realName: asString(match[2]).trim() };
}

function parseNotionId(value) {
	const id = asString(value).trim();
	if (!id) return "";
	const normalized = id.replaceAll("-", "");
	return /^[0-9a-f]{32}$/iu.test(normalized) ? id : "";
}

function getStudentsDbIdFromWorksDb(worksDb, authorPropName) {
	const prop = worksDb?.properties?.[authorPropName];
	if (!prop || prop.type !== "relation") return "";
	return asString(prop?.relation?.database_id).trim();
}

function getRelationDbIdFromDatabase(database, relationPropName, fallbackPropType = "relation") {
	const propName = pickPropertyName(database, [relationPropName], fallbackPropType);
	const prop = database?.properties?.[propName];
	if (!prop || prop.type !== "relation") return "";
	return asString(prop?.relation?.database_id).trim();
}

function getProperty(page, propName) {
	if (!propName) return null;
	return page?.properties?.[propName] || null;
}

async function buildStudentsIndex({
	token,
	worksDbId,
	tagsDbId,
	studentsDbIdHint,
	worksAuthorPropName,
	participantsBaseUrl,
	participantsKey,
}) {
	const worksDb = await notionRequest(token, "GET", `/databases/${worksDbId}`);
	const resolvedAuthorProp = pickPropertyName(
		worksDb,
		[worksAuthorPropName, "作者", "生徒", "生徒名"],
		"",
	);
	const studentsDbId = studentsDbIdHint || getStudentsDbIdFromWorksDb(worksDb, resolvedAuthorProp);
	let resolvedStudentsDbId = studentsDbId;

	if (!resolvedStudentsDbId) {
		const searchable = await notionSearchDatabases(token);
		let best = { id: "", score: 0 };
		for (const db of searchable) {
			const dbId = asString(db?.id);
			if (!dbId) continue;
			if (dbId === worksDbId || dbId === tagsDbId) continue;
			const props = db?.properties || {};
			const names = Object.keys(props);
			const hasTitle = names.some((name) => props[name]?.type === "title");
			let score = 0;
			if (names.includes("生徒ID")) score += 10;
			if (names.includes("ニックネーム")) score += 4;
			if (names.includes("本名")) score += 4;
			if (names.includes("メールアドレス")) score += 3;
			if (names.includes("予約メール希望")) score += 2;
			if (hasTitle) score += 2;
			if (score > best.score) best = { id: dbId, score };
		}
		if (best.score >= 8) resolvedStudentsDbId = best.id;
	}

	if (!resolvedStudentsDbId) {
		const recordsByStudentId = new Map();
		const base = asString(participantsBaseUrl).replace(/\/$/u, "");
		if (!base) throw new Error("Students DB id could not be resolved and participants base URL is empty");
		const participantsUrl = `${base}/${participantsKey}`;
		const res = await fetch(participantsUrl);
		if (!res.ok) throw new Error(`Students DB id could not be resolved; fallback fetch failed (${res.status}): ${participantsUrl}`);
		const json = await res.json();
		const dates = json?.dates || {};
		for (const groups of Object.values(dates)) {
			if (!Array.isArray(groups)) continue;
			for (const group of groups) {
				const participants = Array.isArray(group?.participants) ? group.participants : [];
				for (const p of participants) {
					const studentId = asString(p?.student_id).trim();
					const parsed = splitStudentNameLabel(asString(p?.display_name).trim());
					const realName = parsed.realName;
					const nickname = asString(parsed.nickname || studentId).trim();
					const displayName = nickname || realName || studentId;
					if (!studentId || !displayName) continue;
					if (!recordsByStudentId.has(studentId)) {
						recordsByStudentId.set(studentId, {
							notion_id: parseNotionId(studentId),
							student_id: studentId,
							nickname,
							real_name: realName,
							display_name: displayName,
						});
					}
				}
			}
		}
		const students = Array.from(recordsByStudentId.values()).sort((a, b) => {
			const byName = a.display_name.localeCompare(b.display_name, "ja");
			if (byName !== 0) return byName;
			return a.student_id.localeCompare(b.student_id, "ja");
		});
		return {
			generated_at: new Date().toISOString(),
			source: {
				fallback: "participants_index",
				participants_url: participantsUrl,
			},
			students,
		};
	}

	const studentsDb = await notionRequest(token, "GET", `/databases/${resolvedStudentsDbId}`);
	const titleProp = pickPropertyName(studentsDb, [env("NOTION_STUDENTS_TITLE_PROP"), "タイトル"], "title");
	const studentIdProp = pickPropertyName(studentsDb, [env("NOTION_STUDENTS_ID_PROP", "生徒ID"), "生徒ID"], "");
	const nicknameProp = pickPropertyName(studentsDb, [env("NOTION_STUDENTS_NICK_PROP", "ニックネーム"), "ニックネーム"], "");
	const realNameProp = pickPropertyName(studentsDb, [env("NOTION_STUDENTS_REALNAME_PROP", "本名"), "本名"], "");

	const queryBody = titleProp ? { sorts: [{ property: titleProp, direction: "ascending" }] } : {};
	const pages = await queryAllPages(token, resolvedStudentsDbId, queryBody);

	const records = [];
	for (const page of pages) {
		const notionId = asString(page?.id).trim();
		if (!notionId) continue;
		const studentId = extractPropertyText(getProperty(page, studentIdProp)).trim();
		const titleText = extractPropertyText(getProperty(page, titleProp)).trim();
		const parsed = splitStudentNameLabel(titleText);
		const realName = extractPropertyText(getProperty(page, realNameProp)).trim() || parsed.realName;
		const nicknameRaw =
			extractPropertyText(getProperty(page, nicknameProp)).trim() ||
			parsed.nickname ||
			titleText;
		const nickname = nicknameRaw;
		const displayName = nickname || realName || studentId || notionId;
		records.push({
			notion_id: notionId,
			student_id: studentId,
			nickname,
			real_name: realName,
			display_name: displayName,
		});
	}

	records.sort((a, b) => {
		const byName = a.display_name.localeCompare(b.display_name, "ja");
		if (byName !== 0) return byName;
		const byStudentId = a.student_id.localeCompare(b.student_id, "ja");
		if (byStudentId !== 0) return byStudentId;
		return a.notion_id.localeCompare(b.notion_id, "ja");
	});

	return {
		generated_at: new Date().toISOString(),
		source: {
			students_db_id: resolvedStudentsDbId,
			title_prop: titleProp,
			student_id_prop: studentIdProp,
			nickname_prop: nicknameProp,
			real_name_prop: realNameProp,
		},
		students: records,
	};
}

async function buildTagsIndex({ token, tagsDbId }) {
	const tagsDb = await notionRequest(token, "GET", `/databases/${tagsDbId}`);

	const titleProp = pickPropertyName(tagsDb, [env("NOTION_TAGS_TITLE_PROP", "タグ"), "タグ"], "title");
	const statusProp = pickPropertyName(tagsDb, [env("NOTION_TAGS_STATUS_PROP", "状態"), "状態"], "");
	const aliasesProp = pickPropertyName(tagsDb, [env("NOTION_TAGS_ALIASES_PROP", "別名"), "別名"], "");
	const mergeToProp = pickPropertyName(tagsDb, [env("NOTION_TAGS_MERGE_TO_PROP", "統合先"), "統合先"], "");
	const parentsProp = pickPropertyName(tagsDb, [env("NOTION_TAGS_PARENTS_PROP", "親タグ"), "親タグ"], "");
	const childrenProp = pickPropertyName(tagsDb, [env("NOTION_TAGS_CHILDREN_PROP", "子タグ"), "子タグ"], "");
	const usageCountProp = pickPropertyName(tagsDb, [env("NOTION_TAGS_USAGE_COUNT_PROP", "作品数"), "作品数"], "");
	const worksRelProp = pickPropertyName(tagsDb, ["作品"], "");

	const pages = await queryAllPages(token, tagsDbId, {});

	const tagsById = new Map();
	for (const page of pages) {
		const id = asString(page?.id).trim();
		if (!id) continue;
		const name = extractPropertyText(getProperty(page, titleProp)).trim();
		if (!name) continue;

		const aliases = extractAliases(getProperty(page, aliasesProp))
			.filter((alias) => alias !== name)
			.filter((alias, index, all) => all.indexOf(alias) === index);

		const mergeTo = extractRelationIds(getProperty(page, mergeToProp))[0] || "";
		const parents = extractRelationIds(getProperty(page, parentsProp));
		const children = extractRelationIds(getProperty(page, childrenProp));
		let usageCount = Math.max(0, Math.floor(extractPropertyNumber(getProperty(page, usageCountProp))));
		if (!usageCount && worksRelProp) {
			const relCount = extractRelationIds(getProperty(page, worksRelProp)).length;
			usageCount = Math.max(0, relCount);
		}

		const statusRaw = extractPropertyText(getProperty(page, statusProp));
		tagsById.set(id, {
			id,
			name,
			aliases,
			status: normalizeStatus(statusRaw),
			merge_to: mergeTo,
			parents,
			children,
			usage_count: usageCount,
		});
	}

	for (const tag of tagsById.values()) {
		for (const parentId of tag.parents) {
			const parent = tagsById.get(parentId);
			if (!parent) continue;
			if (!parent.children.includes(tag.id)) parent.children.push(tag.id);
		}
	}

	const tags = Array.from(tagsById.values()).map((tag) => ({
		...tag,
		parents: [...new Set(tag.parents)].sort((a, b) => a.localeCompare(b, "ja")),
		children: [...new Set(tag.children)].sort((a, b) => a.localeCompare(b, "ja")),
	}));

	tags.sort((a, b) => {
		if (b.usage_count !== a.usage_count) return b.usage_count - a.usage_count;
		return a.name.localeCompare(b.name, "ja");
	});

	return {
		generated_at: new Date().toISOString(),
		source: {
			tags_db_id: tagsDbId,
			title_prop: titleProp,
			status_prop: statusProp,
			aliases_prop: aliasesProp,
			merge_to_prop: mergeToProp,
			parents_prop: parentsProp,
			children_prop: childrenProp,
			usage_count_prop: usageCountProp || worksRelProp,
		},
		tags,
	};
}

async function writeJson(filePath, value) {
	await fs.mkdir(path.dirname(filePath), { recursive: true });
	await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function main() {
	const args = parseArgs(process.argv.slice(2));
	const fallbackEnvFile = path.join(MONOREPO_ROOT, ".env");
	const envFile = args.envFile ? path.resolve(args.envFile) : fallbackEnvFile;

	try {
		await fs.access(envFile);
		await loadEnvFile(envFile);
		console.log(`Loaded env file: ${envFile}`);
	} catch {
		if (args.envFile) throw new Error(`env file not found: ${envFile}`);
	}

	const token = env("NOTION_TOKEN");
	const worksDbId = env("NOTION_WORKS_DB_ID") || env("NOTION_DATABASE_ID");
	let tagsDbId = env("NOTION_TAGS_DB_ID") || env("TAGS_DATABASE_ID");
	const studentsDbIdHint = env("NOTION_STUDENTS_DB_ID");
	const worksAuthorPropName = env("NOTION_WORKS_AUTHOR_PROP", "作者");
	const worksTagsPropName = env("NOTION_WORKS_TAGS_PROP", "タグ");
	const participantsBaseUrl = env("R2_PUBLIC_BASE_URL") || env("R2_PUBLIC_URL");
	const participantsKey = env("PARTICIPANTS_INDEX_KEY", "participants_index.json");

	if (!token || !worksDbId) {
		printHelp();
		throw new Error("Missing required env: NOTION_TOKEN and works database id");
	}

	if (!tagsDbId) {
		const worksDb = await notionRequest(token, "GET", `/databases/${worksDbId}`);
		tagsDbId = getRelationDbIdFromDatabase(worksDb, worksTagsPropName, "relation");
	}
	if (!tagsDbId) {
		throw new Error("Tags database id could not be resolved (set NOTION_TAGS_DB_ID or TAGS_DATABASE_ID)");
	}

	const outDir = path.resolve(args.outDir || path.join(process.cwd(), "tmp", "admin-indexes"));
	const studentsOut = path.join(outDir, "students_index.json");
	const tagsOut = path.join(outDir, "tags_index.json");

	const [studentsIndex, tagsIndex] = await Promise.all([
		buildStudentsIndex({
			token,
			worksDbId,
			tagsDbId,
			studentsDbIdHint,
			worksAuthorPropName,
			participantsBaseUrl,
			participantsKey,
		}),
		buildTagsIndex({ token, tagsDbId }),
	]);

	await writeJson(studentsOut, studentsIndex);
	await writeJson(tagsOut, tagsIndex);

	console.log(`students_index.json: ${studentsIndex.students.length} records -> ${studentsOut}`);
	console.log(`tags_index.json: ${tagsIndex.tags.length} records -> ${tagsOut}`);
}

main().catch((error) => {
	console.error(error?.message || error);
	process.exit(1);
});
