#!/usr/bin/env node

const NOTION_API_BASE = "https://api.notion.com/v1";
const NOTION_VERSION = "2022-06-28";

function parseArgs(argv) {
	const args = {
		apply: false,
		dryRun: true,
		from: "",
		to: "",
		tag: "",
		unpreparedOnly: false,
		max: 0,
	};

	for (let i = 0; i < argv.length; i += 1) {
		const a = argv[i];
		if (a === "--apply") {
			args.apply = true;
			args.dryRun = false;
			continue;
		}
		if (a === "--dry-run") {
			args.apply = false;
			args.dryRun = true;
			continue;
		}
		if (a === "--from") {
			args.from = argv[i + 1] || "";
			i += 1;
			continue;
		}
		if (a === "--to") {
			args.to = argv[i + 1] || "";
			i += 1;
			continue;
		}
		if (a === "--tag") {
			args.tag = argv[i + 1] || "";
			i += 1;
			continue;
		}
		if (a === "--unprepared-only") {
			args.unpreparedOnly = true;
			continue;
		}
		if (a === "--max") {
			args.max = Number(argv[i + 1] || "0") || 0;
			i += 1;
			continue;
		}
		if (a === "-h" || a === "--help") {
			printHelp();
			process.exit(0);
		}
	}

	return args;
}

function printHelp() {
	console.log(`
タグ一括再計算（dry-run / apply）

必要な環境変数:
  NOTION_TOKEN
  NOTION_WORKS_DB_ID
  NOTION_TAGS_DB_ID

使い方:
  node scripts/tag-recalc.mjs --dry-run
  node scripts/tag-recalc.mjs --apply

絞り込み:
  --from YYYY-MM-DD
  --to YYYY-MM-DD
  --tag <tag-page-id>
  --unprepared-only
  --max N
`);
}

function assertYmd(value, label) {
	if (!value) return;
	if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
		throw new Error(`${label} は YYYY-MM-DD 形式で指定してください: ${value}`);
	}
}

function sleep(ms) {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

function asString(value) {
	return typeof value === "string" ? value : "";
}

function isNotionIdLike(value) {
	const s = String(value || "").replaceAll("-", "");
	return /^[0-9a-f]{32}$/i.test(s);
}

function buildHeaders(token) {
	return {
		Authorization: `Bearer ${token}`,
		"Notion-Version": NOTION_VERSION,
		"Content-Type": "application/json",
	};
}

async function notionRequest(token, method, path, body) {
	const res = await fetch(`${NOTION_API_BASE}${path}`, {
		method,
		headers: buildHeaders(token),
		body: body ? JSON.stringify(body) : undefined,
	});
	const contentType = res.headers.get("content-type") || "";
	const isJson = contentType.includes("application/json");
	const data = isJson ? await res.json().catch(() => null) : await res.text().catch(() => null);
	if (!res.ok) {
		const msg = typeof data === "object" && data ? data.message || JSON.stringify(data) : String(data);
		const err = new Error(`Notion API error: ${res.status} ${msg}`);
		err.status = res.status;
		err.data = data;
		throw err;
	}
	return data;
}

function findFirstPropertyNameByType(database, type) {
	const props = database?.properties || {};
	for (const [name, prop] of Object.entries(props)) {
		if (prop?.type === type) return name;
	}
	return "";
}

function pickPropName(database, preferredName, typeFallback) {
	const props = database?.properties || {};
	if (preferredName && props[preferredName]) return preferredName;
	if (typeFallback) {
		const byType = findFirstPropertyNameByType(database, typeFallback);
		if (byType) return byType;
	}
	return "";
}

function extractTitle(page, titlePropName) {
	const parts = page?.properties?.[titlePropName]?.title || [];
	return parts.map((p) => asString(p?.plain_text)).join("");
}

function extractRelationIds(page, propName) {
	const rel = page?.properties?.[propName]?.relation;
	if (!Array.isArray(rel)) return [];
	return rel.map((r) => asString(r?.id)).filter(Boolean);
}

function extractCheckbox(page, propName) {
	return Boolean(page?.properties?.[propName]?.checkbox);
}

function extractDateYmd(page, propName) {
	return asString(page?.properties?.[propName]?.date?.start);
}

async function queryAll(token, dbId, body) {
	const results = [];
	let cursor = "";

	while (true) {
		const payload = { page_size: 100, ...body };
		if (cursor) payload.start_cursor = cursor;
		const data = await notionRequest(token, "POST", `/databases/${dbId}/query`, payload);
		const pageResults = Array.isArray(data?.results) ? data.results : [];
		results.push(...pageResults);
		if (!data?.has_more) break;
		cursor = asString(data?.next_cursor);
		if (!cursor) break;
	}

	return results;
}

function detectParentCycles(tagById) {
	const cycles = [];
	const visiting = new Set();
	const visited = new Set();

	const walk = (id, stack) => {
		if (visited.has(id)) return;
		if (visiting.has(id)) {
			const idx = stack.indexOf(id);
			if (idx >= 0) cycles.push(stack.slice(idx).concat(id));
			return;
		}
		visiting.add(id);
		stack.push(id);

		const parents = tagById.get(id)?.parents || [];
		for (const p of parents) walk(p, stack);

		stack.pop();
		visiting.delete(id);
		visited.add(id);
	};

	for (const id of tagById.keys()) walk(id, []);
	return cycles;
}

function buildMergeResolver(tagById) {
	const memo = new Map();
	return (id) => {
		if (!id) return "";
		if (memo.has(id)) return memo.get(id);
		const visited = new Set();
		let cur = id;
		while (cur && !visited.has(cur)) {
			visited.add(cur);
			const t = tagById.get(cur);
			if (!t) break;
			if (t.status !== "merged") break;
			if (!t.mergeTo) break;
			cur = t.mergeTo;
		}
		memo.set(id, cur);
		return cur;
	};
}

function computeAncestors(tagIds, tagById) {
	const out = new Set();
	const seen = new Set();
	const stack = [...tagIds];
	while (stack.length) {
		const id = stack.pop();
		if (!id || seen.has(id)) continue;
		seen.add(id);
		const parents = tagById.get(id)?.parents || [];
		for (const p of parents) {
			if (!p) continue;
			if (!out.has(p)) out.add(p);
			stack.push(p);
		}
	}
	return out;
}

async function main() {
	const args = parseArgs(process.argv.slice(2));

	const token = process.env.NOTION_TOKEN || "";
	const worksDbId = process.env.NOTION_WORKS_DB_ID || "";
	const tagsDbId = process.env.NOTION_TAGS_DB_ID || "";

	if (!token || !worksDbId || !tagsDbId) {
		printHelp();
		throw new Error("環境変数 NOTION_TOKEN / NOTION_WORKS_DB_ID / NOTION_TAGS_DB_ID が必要です");
	}

	assertYmd(args.from, "--from");
	assertYmd(args.to, "--to");
	if (args.tag && !isNotionIdLike(args.tag)) {
		throw new Error(`--tag は Notion page id を指定してください: ${args.tag}`);
	}

	console.log(`モード: ${args.dryRun ? "dry-run" : "apply"}`);

	const [tagsDb, worksDb] = await Promise.all([
		notionRequest(token, "GET", `/databases/${tagsDbId}`, null),
		notionRequest(token, "GET", `/databases/${worksDbId}`, null),
	]);

	const tagTitleProp = pickPropName(tagsDb, "タグ", "title") || pickPropName(tagsDb, "タグ名", "title");
	const tagStatusProp = pickPropName(tagsDb, "状態", "select");
	const tagMergeToProp = pickPropName(tagsDb, "統合先", "relation");
	const tagParentsProp = pickPropName(tagsDb, "親タグ", "relation");

	if (!tagTitleProp || !tagStatusProp || !tagParentsProp) {
		throw new Error("タグDBのプロパティ名を特定できません（Title/状態/親タグ）");
	}

	const worksTitleProp = pickPropName(worksDb, process.env.NOTION_WORKS_TITLE_PROP || "作品名", "title");
	const worksTagsProp = pickPropName(worksDb, process.env.NOTION_WORKS_TAGS_PROP || "タグ", "relation");
	const worksPreparedProp =
		pickPropName(worksDb, process.env.NOTION_WORKS_READY_PROP || "整備済み", "") ||
		pickPropName(worksDb, "整備済", "") ||
		pickPropName(worksDb, "", "checkbox");
	const worksCompletedProp = pickPropName(worksDb, process.env.NOTION_WORKS_COMPLETED_DATE_PROP || "完成日", "date");

	if (!worksTagsProp) {
		throw new Error("作品DBの「タグ」(Relation) を特定できません");
	}

	console.log(`タグDB: title=${tagTitleProp}, status=${tagStatusProp}, merge_to=${tagMergeToProp || "-"}, parents=${tagParentsProp}`);
	console.log(`作品DB: title=${worksTitleProp || "-"}, tags=${worksTagsProp}, prepared=${worksPreparedProp || "-"}, completed=${worksCompletedProp || "-"}`);

	console.log("タグDBを読み込み中…");
	const tagPages = await queryAll(token, tagsDbId, {});
	const tagById = new Map();
	for (const page of tagPages) {
		const id = asString(page?.id);
		if (!id) continue;
		const name = extractTitle(page, tagTitleProp);
		const status = asString(page?.properties?.[tagStatusProp]?.select?.name) || "active";
		const mergeToIds = tagMergeToProp ? extractRelationIds(page, tagMergeToProp) : [];
		const parents = extractRelationIds(page, tagParentsProp);
		tagById.set(id, {
			id,
			name,
			status,
			mergeTo: mergeToIds[0] || "",
			parents,
		});
	}

	const cycles = detectParentCycles(tagById);
	if (cycles.length) {
		console.warn(`警告: 親子関係に循環が疑われます（${cycles.length}件）`);
		console.warn(`例: ${cycles[0].join(" -> ")}`);
	}

	const mergedIssues = [];
	for (const t of tagById.values()) {
		if (t.status !== "merged") continue;
		if (!t.mergeTo) mergedIssues.push(`mergedだが統合先が空: ${t.id} ${t.name}`);
		else if (!tagById.has(t.mergeTo)) mergedIssues.push(`統合先が存在しない: ${t.id} -> ${t.mergeTo}`);
	}
	if (mergedIssues.length) {
		console.warn(`警告: merged整合性に問題がある可能性があります（${mergedIssues.length}件）`);
		console.warn(`例: ${mergedIssues[0]}`);
	}

	const resolveMerge = buildMergeResolver(tagById);

	console.log("作品DBを読み込み中…");
	const filters = [];
	if (args.unpreparedOnly && worksPreparedProp) {
		filters.push({ property: worksPreparedProp, checkbox: { equals: false } });
	}
	if (args.tag) {
		filters.push({ property: worksTagsProp, relation: { contains: args.tag } });
	}
	if ((args.from || args.to) && worksCompletedProp) {
		if (args.from) filters.push({ property: worksCompletedProp, date: { on_or_after: args.from } });
		if (args.to) filters.push({ property: worksCompletedProp, date: { on_or_before: args.to } });
	}

	const queryBody = {};
	if (filters.length === 1) queryBody.filter = filters[0];
	if (filters.length > 1) queryBody.filter = { and: filters };
	if (worksCompletedProp) queryBody.sorts = [{ property: worksCompletedProp, direction: "descending" }];

	const workPages = await queryAll(token, worksDbId, queryBody);

	console.log(`対象作品: ${workPages.length}件`);
	const changes = [];

	for (const page of workPages) {
		if (args.max > 0 && changes.length >= args.max && args.dryRun) break;
		const id = asString(page?.id);
		if (!id) continue;

		const title = worksTitleProp ? extractTitle(page, worksTitleProp) : "";
		const completed = worksCompletedProp ? extractDateYmd(page, worksCompletedProp) : "";
		const prepared = worksPreparedProp ? extractCheckbox(page, worksPreparedProp) : false;

		const tagIds0 = extractRelationIds(page, worksTagsProp);
		const normalized0 = [];
		const removed = [];
		for (const tid of tagIds0) {
			const resolved = resolveMerge(tid);
			if (resolved && resolved !== tid) removed.push(tid);
			if (resolved) normalized0.push(resolved);
		}
		const set0 = new Set(normalized0);
		const ancestors = computeAncestors(Array.from(set0), tagById);
		for (const a of ancestors) set0.add(a);
		const tagIds1 = Array.from(set0);

		const setRaw0 = new Set(tagIds0);
		const set1 = new Set(tagIds1);
		const add = tagIds1.filter((x) => !setRaw0.has(x));
		const del = tagIds0.filter((x) => !set1.has(resolveMerge(x)));

		const changed = add.length > 0 || removed.length > 0 || del.length > 0;
		if (!changed) continue;

		changes.push({
			id,
			title,
			completed,
			prepared,
			before: tagIds0,
			after: tagIds1,
			add,
			del: Array.from(new Set([...removed, ...del])),
		});
	}

	console.log(`変更対象: ${changes.length}件`);

	if (args.dryRun) {
		const samples = changes.slice(0, 10);
		for (const c of samples) {
			console.log(`- ${c.completed || "-"} ${c.title || "（無題）"} (${c.id})`);
			console.log(`  + add: ${c.add.length} / - del: ${c.del.length}`);
		}
		console.log("dry-run のため反映は行いません。");
		return;
	}

	console.log("apply: Notionへ反映します（レート制限を考慮して逐次）…");
	let done = 0;
	for (const c of changes) {
		await notionRequest(token, "PATCH", `/pages/${c.id}`, {
			properties: {
				[worksTagsProp]: { relation: c.after.map((id) => ({ id })) },
			},
		});
		done += 1;
		if (done % 10 === 0) console.log(`進捗: ${done}/${changes.length}`);
		await sleep(350);
	}

	console.log(`完了: ${done}件反映しました`);
}

main().catch((err) => {
	console.error(err?.message || err);
	process.exit(1);
});
