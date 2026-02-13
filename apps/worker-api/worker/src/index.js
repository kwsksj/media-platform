const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Access-Control-Max-Age": "86400",
};

function withCors(headers = {}) {
  return { ...CORS_HEADERS, ...headers };
}

function jsonResponse(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: withCors({
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...headers,
    }),
  });
}

function errorResponse(status, message) {
  return jsonResponse({ error: message }, status);
}

function okResponse(data, status = 200) {
  return jsonResponse({ ok: true, ...data }, status);
}

function badRequest(message) {
  return jsonResponse({ ok: false, error: message }, 400);
}

function serverError(message) {
  return jsonResponse({ ok: false, error: message }, 500);
}

function parseIds(url) {
  const raw = url.searchParams.get("ids") || "";
  if (!raw.trim()) return [];
  return raw
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function normalizeCount(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return 0;
  return Math.max(0, Math.floor(num));
}

async function handleGetStars(url, env) {
  if (!env.STAR_KV) return errorResponse(500, "KV binding not configured");
  const ids = parseIds(url);
  if (ids.length === 0) return jsonResponse({ stars: {} });

  const entries = await Promise.all(
    ids.map(async (id) => {
      const raw = await env.STAR_KV.get(`star:${id}`);
      return [id, normalizeCount(raw)];
    })
  );

  return jsonResponse({ stars: Object.fromEntries(entries) });
}

async function handlePostStar(request, env) {
  if (!env.STAR_KV) return errorResponse(500, "KV binding not configured");
  let body;
  try {
    body = await request.json();
  } catch (error) {
    return errorResponse(400, "invalid json");
  }

  const id = typeof body?.id === "string" ? body.id.trim() : "";
  if (!id) return errorResponse(400, "invalid id");

  const delta = Number.isFinite(Number(body?.delta)) ? Number(body.delta) : 1;
  const key = `star:${id}`;

  const currentRaw = await env.STAR_KV.get(key);
  const current = normalizeCount(currentRaw);
  const next = normalizeCount(current + delta);

  await env.STAR_KV.put(key, String(next));
  return jsonResponse({ id, stars: next });
}

function getEnvString(env, key, fallback = "") {
  const value = env?.[key];
  if (typeof value !== "string") return fallback;
  return value.trim();
}

function getBearerToken(request) {
  const raw = asString(request.headers.get("Authorization")).trim();
  const match = raw.match(/^Bearer\s+(.+)$/i);
  return match ? asString(match[1]).trim() : "";
}

function timingSafeEqual(a, b) {
  const encoder = new TextEncoder();
  const aBuf = encoder.encode(a);
  const bBuf = encoder.encode(b);

  // Cloudflare Workers: crypto.subtle.timingSafeEqual
  if (typeof crypto !== "undefined" && crypto.subtle && typeof crypto.subtle.timingSafeEqual === "function") {
    if (aBuf.byteLength !== bBuf.byteLength) {
      crypto.subtle.timingSafeEqual(bBuf, bBuf);
      return false;
    }
    return crypto.subtle.timingSafeEqual(aBuf, bBuf);
  }

  // Fallback without Node.js compatibility flags.
  let result = aBuf.byteLength ^ bBuf.byteLength;
  const maxLen = Math.max(aBuf.byteLength, bBuf.byteLength);
  for (let i = 0; i < maxLen; i++) {
    const av = i < aBuf.byteLength ? aBuf[i] : 0;
    const bv = i < bBuf.byteLength ? bBuf[i] : 0;
    result |= av ^ bv;
  }
  return result === 0;
}

function requireAdminAuthorization(request, env) {
  const expectedToken = getEnvString(env, "ADMIN_API_TOKEN");
  if (!expectedToken) {
    return serverError("ADMIN_API_TOKEN not configured");
  }

  const actualToken = getBearerToken(request);
  if (!actualToken || !timingSafeEqual(actualToken, expectedToken)) {
    return jsonResponse({ ok: false, error: "unauthorized" }, 401);
  }

  return null;
}

function getWorksProps(env) {
  return {
    title: getEnvString(env, "NOTION_WORKS_TITLE_PROP", "作品名"),
    images: getEnvString(env, "NOTION_WORKS_IMAGES_PROP", "画像"),
    completedDate: getEnvString(env, "NOTION_WORKS_COMPLETED_DATE_PROP", "完成日"),
    classroom: getEnvString(env, "NOTION_WORKS_CLASSROOM_PROP", "教室"),
    venue: getEnvString(env, "NOTION_WORKS_VENUE_PROP", "会場"),
    author: getEnvString(env, "NOTION_WORKS_AUTHOR_PROP", "作者"),
    caption: getEnvString(env, "NOTION_WORKS_CAPTION_PROP", "キャプション"),
    tags: getEnvString(env, "NOTION_WORKS_TAGS_PROP", "タグ"),
    ready: getEnvString(env, "NOTION_WORKS_READY_PROP", "整備済"),
  };
}

function getTagsProps(env) {
  return {
    title: getEnvString(env, "NOTION_TAGS_TITLE_PROP", "タグ"),
    status: getEnvString(env, "NOTION_TAGS_STATUS_PROP", "状態"),
  };
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

function getPageProperty(page, propName) {
  if (!propName) return null;
  return page?.properties?.[propName] || null;
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
  if (type === "number") return Number.isFinite(prop.number) ? String(prop.number) : "";
  if (type === "formula") {
    const formula = prop.formula;
    if (!formula) return "";
    if (formula.type === "string") return asString(formula.string).trim();
    if (formula.type === "number") return Number.isFinite(formula.number) ? String(formula.number) : "";
    if (formula.type === "boolean") return formula.boolean ? "true" : "false";
    return "";
  }
  if (type === "rollup") {
    const rollup = prop.rollup;
    if (!rollup) return "";
    if (rollup.type === "number") return Number.isFinite(rollup.number) ? String(rollup.number) : "";
    if (rollup.type === "array") return String(Array.isArray(rollup.array) ? rollup.array.length : 0);
    return "";
  }
  return "";
}

function extractPropertyNumber(prop) {
  if (!prop || typeof prop !== "object") return 0;
  const type = prop.type;
  if (type === "number") return Number.isFinite(prop.number) ? prop.number : 0;
  if (type === "formula") {
    const formula = prop.formula;
    if (!formula) return 0;
    if (formula.type === "number" && Number.isFinite(formula.number)) return formula.number;
    if (formula.type === "string") {
      const parsed = Number(formula.string);
      return Number.isFinite(parsed) ? parsed : 0;
    }
    return 0;
  }
  if (type === "rollup") {
    const rollup = prop.rollup;
    if (!rollup) return 0;
    if (rollup.type === "number" && Number.isFinite(rollup.number)) return rollup.number;
    if (rollup.type === "array") return Array.isArray(rollup.array) ? rollup.array.length : 0;
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

function normalizeTagStatus(raw) {
  const value = asString(raw).trim().toLowerCase();
  if (!value) return "active";
  if (value.includes("merged") || value.includes("統合")) return "merged";
  if (value.includes("hidden") || value.includes("非表示")) return "hidden";
  return "active";
}

async function queryAllDatabasePages(env, databaseId, queryBody = {}) {
  const pages = [];
  let cursor = "";

  while (true) {
    const body = { page_size: 100, ...queryBody };
    if (cursor) body.start_cursor = cursor;
    const res = await notionFetch(env, `/databases/${databaseId}/query`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (!res.ok) return { ok: false, data: res.data };

    const results = Array.isArray(res.data?.results) ? res.data.results : [];
    pages.push(...results);
    if (!res.data?.has_more) break;
    cursor = asString(res.data?.next_cursor);
    if (!cursor) break;
  }

  return { ok: true, pages };
}

function buildTagsIndexFromNotion(env, tagsDbId, tagsDb, pages) {
  const titleProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_TITLE_PROP", "タグ"), "タグ"], "title");
  const statusProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_STATUS_PROP", "状態"), "状態"], "");
  const aliasesProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_ALIASES_PROP", "別名"), "別名"], "");
  const mergeToProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_MERGE_TO_PROP", "統合先"), "統合先"], "");
  const parentsProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_PARENTS_PROP", "親タグ"), "親タグ"], "");
  const childrenProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_CHILDREN_PROP", "子タグ"), "子タグ"], "");
  const usageCountProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_USAGE_COUNT_PROP", "作品数"), "作品数"], "");
  const worksRelProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_WORKS_REL_PROP", "作品"), "作品"], "");

  const tagsById = new Map();
  for (const page of pages) {
    const id = asString(page?.id).trim();
    if (!id) continue;

    const name = extractPropertyText(getPageProperty(page, titleProp)).trim();
    if (!name) continue;

    const aliases = extractAliases(getPageProperty(page, aliasesProp))
      .filter((alias) => alias !== name)
      .filter((alias, index, all) => all.indexOf(alias) === index);

    const mergeTo = extractRelationIds(getPageProperty(page, mergeToProp))[0] || "";
    const parents = extractRelationIds(getPageProperty(page, parentsProp));
    const children = extractRelationIds(getPageProperty(page, childrenProp));

    let usageCount = Math.max(0, Math.floor(extractPropertyNumber(getPageProperty(page, usageCountProp))));
    if (!usageCount && worksRelProp) {
      usageCount = Math.max(0, extractRelationIds(getPageProperty(page, worksRelProp)).length);
    }

    const statusRaw = extractPropertyText(getPageProperty(page, statusProp));
    tagsById.set(id, {
      id,
      name,
      aliases,
      status: normalizeTagStatus(statusRaw),
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

function findFirstDatabasePropertyNameByType(database, type) {
  const props = database?.properties || {};
  for (const [name, prop] of Object.entries(props)) {
    if (prop?.type === type) return name;
  }
  return "";
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

function isNonEmptyString(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function asString(value) {
  return typeof value === "string" ? value : "";
}

function firstNChars(value, n) {
  return Array.from(asString(value).trim()).slice(0, n).join("");
}

function splitStudentNameLabel(value) {
  const raw = asString(value).trim();
  if (!raw) return { nickname: "", realName: "" };
  const match = raw.match(/^(.+?)\s*[|｜]\s*(.+)$/u);
  if (!match) return { nickname: raw, realName: "" };
  return { nickname: asString(match[1]).trim(), realName: asString(match[2]).trim() };
}

function normalizeNickname(value, realName) {
  const nickname = asString(value).trim();
  const real = asString(realName).trim();
  if (!nickname) return "";
  if (!real) return nickname;
  if (nickname !== real) return nickname;
  return firstNChars(real, 2) || nickname;
}

function normalizeYmd(value) {
  const raw = asString(value).trim();
  if (!raw) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  return "";
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function uniqueIds(ids) {
  if (!Array.isArray(ids)) return [];
  const out = [];
  const seen = new Set();
  for (const raw of ids) {
    const id = asString(raw).trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}

function isSameIdSet(a, b) {
  const setA = new Set(uniqueIds(a));
  const setB = new Set(uniqueIds(b));
  if (setA.size !== setB.size) return false;
  for (const id of setA) {
    if (!setB.has(id)) return false;
  }
  return true;
}

function buildMergeResolver(tagById) {
  const memo = new Map();
  return (id) => {
    const key = asString(id).trim();
    if (!key) return "";
    if (memo.has(key)) return memo.get(key);
    const visited = new Set();
    let current = key;
    while (current && !visited.has(current)) {
      visited.add(current);
      const tag = tagById.get(current);
      if (!tag) break;
      if (tag.status !== "merged") break;
      const mergeTo = asString(tag.mergeTo).trim();
      if (!mergeTo) break;
      current = mergeTo;
    }
    memo.set(key, current);
    return current;
  };
}

function detectParentCycles(tagById, resolveMerge) {
  const cycles = [];
  const visiting = new Set();
  const visited = new Set();

  const walk = (id, stack) => {
    if (!id) return;
    if (visited.has(id)) return;
    if (visiting.has(id)) {
      const idx = stack.indexOf(id);
      if (idx >= 0) cycles.push(stack.slice(idx).concat(id));
      return;
    }

    visiting.add(id);
    stack.push(id);

    const parents = tagById.get(id)?.parents || [];
    for (const parentIdRaw of parents) {
      const parentId = resolveMerge(parentIdRaw);
      if (!parentId) continue;
      walk(parentId, stack);
    }

    stack.pop();
    visiting.delete(id);
    visited.add(id);
  };

  for (const id of tagById.keys()) {
    walk(id, []);
  }

  return cycles;
}

function computeAncestorTagIds(tagIds, tagById, resolveMerge) {
  const out = new Set();
  const visited = new Set();
  const stack = [...tagIds];

  while (stack.length > 0) {
    const current = resolveMerge(stack.pop());
    if (!current || visited.has(current)) continue;
    visited.add(current);

    const parents = tagById.get(current)?.parents || [];
    for (const parentRaw of parents) {
      const parentId = resolveMerge(parentRaw);
      if (!parentId) continue;
      if (!out.has(parentId)) out.add(parentId);
      stack.push(parentId);
    }
  }

  return out;
}

function buildNotionHeaders(env) {
  const token = getEnvString(env, "NOTION_TOKEN");
  if (!token) return null;
  return {
    Authorization: `Bearer ${token}`,
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
  };
}

async function notionFetch(env, path, init) {
  const headers = buildNotionHeaders(env);
  if (!headers) return { ok: false, status: 500, data: { error: "NOTION_TOKEN not configured" } };

  const res = await fetch(`https://api.notion.com/v1${path}`, {
    ...init,
    headers: {
      ...headers,
      ...(init?.headers || {}),
    },
  });

  const contentType = res.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const data = isJson ? await res.json().catch(() => null) : await res.text().catch(() => null);
  return { ok: res.ok, status: res.status, data };
}

function getNotionFileUrl(file) {
  if (!file || typeof file !== "object") return "";
  if (file.type === "external") return asString(file.external?.url);
  if (file.type === "file") return asString(file.file?.url);
  return "";
}

function simplifyNotionFiles(files) {
  if (!Array.isArray(files)) return [];
  return files
    .map((f) => ({
      name: asString(f?.name),
      type: asString(f?.type),
      url: getNotionFileUrl(f),
    }))
    .filter((f) => f.url);
}

function notionTitle(content) {
  return {
    title: [
      {
        type: "text",
        text: { content: asString(content) },
      },
    ],
  };
}

function notionRichText(content) {
  const text = asString(content);
  if (!text) return { rich_text: [] };
  return {
    rich_text: [
      {
        type: "text",
        text: { content: text },
      },
    ],
  };
}

function notionSelect(value) {
  const name = asString(value).trim();
  if (!name) return { select: null };
  return { select: { name } };
}

function notionStatus(value) {
  const name = asString(value).trim();
  if (!name) return { status: null };
  return { status: { name } };
}

function notionDate(ymd) {
  const date = normalizeYmd(ymd);
  if (!date) return { date: null };
  return { date: { start: date } };
}

function notionCheckbox(value) {
  return { checkbox: Boolean(value) };
}

function notionRelation(ids) {
  if (!Array.isArray(ids)) return { relation: [] };
  const relation = ids
    .filter((id) => typeof id === "string" && id.trim())
    .map((id) => ({ id: id.trim() }));
  return { relation };
}

function notionExternalFiles(files) {
  if (!Array.isArray(files)) return { files: [] };
  const notionFiles = files
    .map((f) => {
      if (!f || typeof f !== "object") return null;
      const url = asString(f.url).trim();
      if (!url) return null;
      const name = asString(f.name).trim() || url.split("/").pop() || "image";
      const type = asString(f.type).trim();
      if (type === "file") {
        return { name, type: "file", file: { url } };
      }
      return { name, type: "external", external: { url } };
    })
    .filter(Boolean);
  return { files: notionFiles };
}

function listNotionSelectLikeOptionNames(propSchema) {
  if (!propSchema || typeof propSchema !== "object") return [];
  if (propSchema.type === "status") {
    return (propSchema.status?.options || [])
      .map((opt) => asString(opt?.name).trim())
      .filter(Boolean);
  }
  if (propSchema.type === "select") {
    return (propSchema.select?.options || [])
      .map((opt) => asString(opt?.name).trim())
      .filter(Boolean);
  }
  return [];
}

function resolveDefaultTagStatusName(env, statusPropSchema) {
  const preferred = asString(getEnvString(env, "NOTION_TAGS_DEFAULT_STATUS", "active")).trim();
  const options = listNotionSelectLikeOptionNames(statusPropSchema);
  if (options.length === 0) return preferred;

  const exact = options.find((name) => name.toLowerCase() === preferred.toLowerCase());
  if (exact) return exact;

  const activeLike = options.find((name) => normalizeTagStatus(name) === "active");
  if (activeLike) return activeLike;

  return options[0] || preferred;
}

function pickWorkProperties(env, payload) {
  const worksProps = getWorksProps(env);
  const props = {};

  if ("title" in payload && worksProps.title) props[worksProps.title] = notionTitle(payload.title);
  if ("completedDate" in payload && worksProps.completedDate) props[worksProps.completedDate] = notionDate(payload.completedDate);
  if ("classroom" in payload && worksProps.classroom) props[worksProps.classroom] = notionSelect(payload.classroom);
  if ("venue" in payload && worksProps.venue) props[worksProps.venue] = notionSelect(payload.venue);
  if ("caption" in payload && worksProps.caption) props[worksProps.caption] = notionRichText(payload.caption);
  if ("ready" in payload && worksProps.ready) props[worksProps.ready] = notionCheckbox(payload.ready);

  if ("authorIds" in payload && worksProps.author) {
    const ids = Array.isArray(payload.authorIds) ? payload.authorIds : [];
    props[worksProps.author] = notionRelation(ids);
  } else if ("authorId" in payload && worksProps.author) {
    props[worksProps.author] = notionRelation(payload.authorId ? [payload.authorId] : []);
  }
  if ("tagIds" in payload && worksProps.tags)
    props[worksProps.tags] = notionRelation(Array.isArray(payload.tagIds) ? payload.tagIds : []);
  if ("images" in payload && worksProps.images) props[worksProps.images] = notionExternalFiles(payload.images);

  return props;
}

function simplifyWorkFromNotionPage(env, page) {
  const worksProps = getWorksProps(env);
  const props = page?.properties || {};
  const titleParts = (worksProps.title ? props[worksProps.title]?.title : null) || [];
  const title = titleParts.map((t) => asString(t?.plain_text)).join("");

  const completedDate = worksProps.completedDate ? asString(props[worksProps.completedDate]?.date?.start) : "";
  const classroom = worksProps.classroom ? asString(props[worksProps.classroom]?.select?.name) : "";
  const venue = worksProps.venue ? asString(props[worksProps.venue]?.select?.name) : "";

  const authorRelation = worksProps.author ? props[worksProps.author]?.relation : null;
  const authorIds = Array.isArray(authorRelation)
    ? authorRelation.map((r) => asString(r?.id)).filter(Boolean)
    : [];
  const tagsRelation = worksProps.tags ? props[worksProps.tags]?.relation : null;
  const tagIds = Array.isArray(tagsRelation)
    ? tagsRelation.map((r) => asString(r?.id)).filter(Boolean)
    : [];

  const captionParts = (worksProps.caption ? props[worksProps.caption]?.rich_text : null) || [];
  const caption = captionParts.map((t) => asString(t?.plain_text)).join("");

  const ready = worksProps.ready ? Boolean(props[worksProps.ready]?.checkbox) : false;
  const imagesRaw = (worksProps.images ? props[worksProps.images]?.files : null) || [];
  const images = simplifyNotionFiles(imagesRaw);

  return {
    id: asString(page?.id),
    title,
    completedDate,
    classroom,
    venue,
    authorIds,
    tagIds,
    caption,
    ready,
    images,
  };
}

async function handleNotionSchema(env) {
  const worksDbId = getEnvString(env, "NOTION_WORKS_DB_ID");
  if (!worksDbId) return serverError("NOTION_WORKS_DB_ID not configured");

  const res = await notionFetch(env, `/databases/${worksDbId}`, { method: "GET" });
  if (!res.ok) {
    return jsonResponse({ ok: false, error: "failed to fetch notion database", detail: res.data }, 500);
  }

  const properties = res.data?.properties || {};
  const worksProps = getWorksProps(env);
  const classroomOptions = worksProps.classroom
    ? (properties[worksProps.classroom]?.select?.options || []).map((o) => asString(o?.name)).filter(Boolean)
    : [];
  const venueOptions = worksProps.venue
    ? (properties[worksProps.venue]?.select?.options || []).map((o) => asString(o?.name)).filter(Boolean)
    : [];
  const authorProp = worksProps.author ? properties[worksProps.author] : null;
  const supportsAuthor = Boolean(authorProp && authorProp.type === "relation");
  const supportsVenue = Boolean(worksProps.venue && properties[worksProps.venue]);

  return okResponse({ classroomOptions, venueOptions, supportsAuthor, supportsVenue });
}

async function handleNotionListWorks(url, env) {
  const worksDbId = getEnvString(env, "NOTION_WORKS_DB_ID");
  if (!worksDbId) return serverError("NOTION_WORKS_DB_ID not configured");

  const worksProps = getWorksProps(env);
  const unprepared = url.searchParams.get("unprepared") === "1";
  const query = asString(url.searchParams.get("q")).trim();
  const cursor = asString(url.searchParams.get("cursor")).trim();

  const body = { page_size: 100 };
  if (worksProps.completedDate) {
    body.sorts = [{ property: worksProps.completedDate, direction: "descending" }];
  }

  const filters = [];
  if (unprepared) {
    if (worksProps.ready) filters.push({ property: worksProps.ready, checkbox: { equals: false } });
  }
  if (query) {
    if (worksProps.title) filters.push({ property: worksProps.title, title: { contains: query } });
  }

  if (filters.length === 1) body.filter = filters[0];
  if (filters.length > 1) body.filter = { and: filters };
  if (cursor) body.start_cursor = cursor;

  const res = await notionFetch(env, `/databases/${worksDbId}/query`, {
    method: "POST",
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    return jsonResponse({ ok: false, error: "failed to query notion database", detail: res.data }, 500);
  }

  const results = Array.isArray(res.data?.results) ? res.data.results.map((page) => simplifyWorkFromNotionPage(env, page)) : [];
  return okResponse({
    results,
    nextCursor: res.data?.has_more ? asString(res.data?.next_cursor) : "",
  });
}

async function handleNotionSearchStudents(url, env) {
  const worksDbId = getEnvString(env, "NOTION_WORKS_DB_ID");
  if (!worksDbId) return serverError("NOTION_WORKS_DB_ID not configured");

  const q = asString(url.searchParams.get("q")).trim();
  if (!q) return badRequest("missing q");

  let studentsDbId = getEnvString(env, "NOTION_STUDENTS_DB_ID");
  if (!studentsDbId) {
    const worksProps = getWorksProps(env);
    if (!worksProps.author) return serverError("NOTION_WORKS_AUTHOR_PROP not configured");
    const worksDbRes = await notionFetch(env, `/databases/${worksDbId}`, { method: "GET" });
    if (!worksDbRes.ok) return jsonResponse({ ok: false, error: "failed to fetch works database", detail: worksDbRes.data }, 500);
    const rel = worksDbRes.data?.properties?.[worksProps.author]?.relation;
    studentsDbId = asString(rel?.database_id);
  }

  if (!studentsDbId) return serverError("students database id not found");

  const studentsDbRes = await notionFetch(env, `/databases/${studentsDbId}`, { method: "GET" });
  if (!studentsDbRes.ok) return jsonResponse({ ok: false, error: "failed to fetch students database", detail: studentsDbRes.data }, 500);

  const titleProp = findFirstDatabasePropertyNameByType(studentsDbRes.data, "title");
  if (!titleProp) return serverError("students title property not found");
  const nicknameProp = studentsDbRes.data?.properties?.["ニックネーム"] ? "ニックネーム" : "";
  const realNameProp = studentsDbRes.data?.properties?.["本名"] ? "本名" : "";

  const queryRes = await notionFetch(env, `/databases/${studentsDbId}/query`, {
    method: "POST",
    body: JSON.stringify({
      page_size: 20,
      filter: {
        property: titleProp,
        title: { contains: q },
      },
      sorts: [{ property: titleProp, direction: "ascending" }],
    }),
  });

  if (!queryRes.ok) return jsonResponse({ ok: false, error: "failed to query students database", detail: queryRes.data }, 500);

  const results = Array.isArray(queryRes.data?.results)
    ? queryRes.data.results.map((page) => {
        const id = asString(page?.id);
        const parts = page?.properties?.[titleProp]?.title || [];
        const title = parts.map((t) => asString(t?.plain_text)).join("").trim();
        const parsed = splitStudentNameLabel(title);
        const realName = (realNameProp ? extractPropertyText(getPageProperty(page, realNameProp)) : "").trim() || parsed.realName;
        const nicknameRaw = (nicknameProp ? extractPropertyText(getPageProperty(page, nicknameProp)) : "").trim() || parsed.nickname || title;
        const nickname = normalizeNickname(nicknameRaw, realName) || parsed.nickname || title;
        const name = realName ? `${nickname}｜${realName}` : nickname;
        return id && name ? { id, name, nickname, real_name: realName } : null;
      }).filter(Boolean)
    : [];

  return okResponse({ results });
}

async function handleNotionCreateWork(request, env) {
  const worksDbId = getEnvString(env, "NOTION_WORKS_DB_ID");
  if (!worksDbId) return serverError("NOTION_WORKS_DB_ID not configured");

  const payload = await readJson(request);
  if (!payload || typeof payload !== "object") return badRequest("invalid json");

  const worksProps = getWorksProps(env);
  const props = pickWorkProperties(env, payload);
  if (worksProps.title && !(worksProps.title in props)) props[worksProps.title] = notionTitle(payload.title || "");

  const res = await notionFetch(env, "/pages", {
    method: "POST",
    body: JSON.stringify({
      parent: { database_id: worksDbId },
      properties: props,
    }),
  });

  if (!res.ok) {
    return jsonResponse({ ok: false, error: "failed to create notion page", detail: res.data }, 500);
  }

  return okResponse({ id: asString(res.data?.id) }, 201);
}

async function handleNotionUpdateWork(request, env) {
  const payload = await readJson(request);
  if (!payload || typeof payload !== "object") return badRequest("invalid json");
  const id = asString(payload.id).trim();
  if (!id) return badRequest("missing id");

  const props = pickWorkProperties(env, payload);
  const body = {};
  if (Object.keys(props).length > 0) body.properties = props;

  if ("archived" in payload) body.archived = Boolean(payload.archived);

  if (Object.keys(body).length === 0) return badRequest("no updates");

  const res = await notionFetch(env, `/pages/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    return jsonResponse({ ok: false, error: "failed to update notion page", detail: res.data }, 500);
  }

  return okResponse({ id });
}

async function handleNotionCreateTag(request, env) {
  const tagsDbId = getEnvString(env, "NOTION_TAGS_DB_ID");
  if (!tagsDbId) return serverError("NOTION_TAGS_DB_ID not configured");

  const payload = await readJson(request);
  if (!payload || typeof payload !== "object") return badRequest("invalid json");
  const name = asString(payload.name).trim();
  if (!name) return badRequest("missing name");
  const parentIds = uniqueIds(Array.isArray(payload.parentIds) ? payload.parentIds : []);
  const childIds = uniqueIds(Array.isArray(payload.childIds) ? payload.childIds : []);

  const tagsDbRes = await notionFetch(env, `/databases/${tagsDbId}`, { method: "GET" });
  if (!tagsDbRes.ok) {
    return jsonResponse({ ok: false, error: "failed to fetch tags database", detail: tagsDbRes.data }, 500);
  }
  const tagsDb = tagsDbRes.data;
  const tagsProps = getTagsProps(env);
  const titleProp = pickPropertyName(tagsDb, [tagsProps.title, "タグ"], "title");
  const statusProp = pickPropertyName(tagsDb, [tagsProps.status, "状態"], "");
  const parentsProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_PARENTS_PROP", "親タグ"), "親タグ"], "");
  const childrenProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_CHILDREN_PROP", "子タグ"), "子タグ"], "");
  if (parentIds.length > 0 && !parentsProp) return badRequest("親タグプロパティが見つかりません");
  if (childIds.length > 0 && !childrenProp) return badRequest("子タグプロパティが見つかりません");
  const properties = {};
  properties[titleProp || tagsProps.title || "タグ"] = notionTitle(name);
  if (parentsProp && parentIds.length > 0) properties[parentsProp] = notionRelation(parentIds);
  if (childrenProp && childIds.length > 0) properties[childrenProp] = notionRelation(childIds);

  let statusName = "";
  if (statusProp) {
    const statusPropSchema = tagsDb?.properties?.[statusProp] || null;
    const defaultStatusName = resolveDefaultTagStatusName(env, statusPropSchema);
    if (defaultStatusName) {
      statusName = defaultStatusName;
      if (statusPropSchema?.type === "status") {
        properties[statusProp] = notionStatus(defaultStatusName);
      } else {
        properties[statusProp] = notionSelect(defaultStatusName);
      }
    }
  }

  const res = await notionFetch(env, "/pages", {
    method: "POST",
    body: JSON.stringify({
      parent: { database_id: tagsDbId },
      properties,
    }),
  });

  if (!res.ok) {
    return jsonResponse({ ok: false, error: "failed to create notion tag", detail: res.data }, 500);
  }

  return okResponse(
    {
      id: asString(res.data?.id),
      name,
      status: statusName || "active",
      parents: parentIds,
      children: childIds,
      aliases: [],
      merge_to: "",
      usage_count: 0,
    },
    201,
  );
}

async function handleNotionUpdateTag(request, env) {
  const tagsDbId = getEnvString(env, "NOTION_TAGS_DB_ID");
  if (!tagsDbId) return serverError("NOTION_TAGS_DB_ID not configured");

  const payload = await readJson(request);
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return badRequest("invalid json");

  const tagsDbRes = await notionFetch(env, `/databases/${tagsDbId}`, { method: "GET" });
  if (!tagsDbRes.ok) {
    return jsonResponse({ ok: false, error: "failed to fetch tags database", detail: tagsDbRes.data }, 500);
  }
  const tagsDb = tagsDbRes.data;
  const tagsProps = getTagsProps(env);
  const titleProp = pickPropertyName(tagsDb, [tagsProps.title, "タグ"], "title");
  const parentsProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_PARENTS_PROP", "親タグ"), "親タグ"], "");
  const childrenProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_CHILDREN_PROP", "子タグ"), "子タグ"], "");

  const loadTagPage = async (id) => {
    const res = await notionFetch(env, `/pages/${id}`, { method: "GET" });
    if (!res.ok) {
      return { ok: false, detail: res.data };
    }
    return { ok: true, page: res.data };
  };

  const patchTagRelations = async ({ id, addParentIds = [], addChildIds = [] }) => {
    const tagId = asString(id).trim();
    if (!tagId) return { ok: false, error: "missing tag id" };
    const parentIds = uniqueIds(addParentIds).filter((value) => value !== tagId);
    const childIds = uniqueIds(addChildIds).filter((value) => value !== tagId);
    if (parentIds.length === 0 && childIds.length === 0) return { ok: false, error: "no relation updates" };
    if (parentIds.length > 0 && !parentsProp) return { ok: false, error: "parent relation property not found" };
    if (childIds.length > 0 && !childrenProp) return { ok: false, error: "child relation property not found" };

    const loaded = await loadTagPage(tagId);
    if (!loaded.ok) {
      return { ok: false, error: "failed to fetch tag page", detail: loaded.detail };
    }

    const page = loaded.page;
    const currentParents = parentsProp ? extractRelationIds(getPageProperty(page, parentsProp)) : [];
    const currentChildren = childrenProp ? extractRelationIds(getPageProperty(page, childrenProp)) : [];
    const nextParents = uniqueIds([...currentParents, ...parentIds]);
    const nextChildren = uniqueIds([...currentChildren, ...childIds]);
    const parentsChanged = parentIds.length > 0 && nextParents.length !== currentParents.length;
    const childrenChanged = childIds.length > 0 && nextChildren.length !== currentChildren.length;

    if (!parentsChanged && !childrenChanged) {
      return {
        ok: true,
        tag: {
          id: tagId,
          name: extractPropertyText(getPageProperty(page, titleProp)),
          parents: currentParents,
          children: currentChildren,
        },
      };
    }

    const properties = {};
    if (parentsProp && parentsChanged) properties[parentsProp] = notionRelation(nextParents);
    if (childrenProp && childrenChanged) properties[childrenProp] = notionRelation(nextChildren);

    const patchRes = await notionFetch(env, `/pages/${tagId}`, {
      method: "PATCH",
      body: JSON.stringify({ properties }),
    });
    if (!patchRes.ok) {
      return { ok: false, error: "failed to update tag page", detail: patchRes.data };
    }

    return {
      ok: true,
      tag: {
        id: tagId,
        name: extractPropertyText(getPageProperty(page, titleProp)),
        parents: nextParents,
        children: nextChildren,
      },
    };
  };

  const directTagId = asString(payload.id).trim();
  if (directTagId) {
    const addParentIds = Array.isArray(payload.addParentIds) ? payload.addParentIds : [];
    const addChildIds = Array.isArray(payload.addChildIds) ? payload.addChildIds : [];
    const updated = await patchTagRelations({
      id: directTagId,
      addParentIds,
      addChildIds,
    });
    if (!updated.ok) {
      return jsonResponse(
        { ok: false, error: updated.error || "failed to update tag relation", detail: updated.detail || null },
        500,
      );
    }
    return okResponse(updated.tag);
  }

  const parentId = asString(payload.parentId).trim();
  const childId = asString(payload.childId).trim();
  if (!parentId || !childId) return badRequest("missing parentId or childId");
  if (parentId === childId) return badRequest("parent and child must be different");

  const childUpdated = await patchTagRelations({ id: childId, addParentIds: [parentId] });
  if (!childUpdated.ok) {
    return jsonResponse(
      { ok: false, error: childUpdated.error || "failed to update child tag relation", detail: childUpdated.detail || null },
      500,
    );
  }

  let parentUpdated = null;
  if (childrenProp) {
    const result = await patchTagRelations({ id: parentId, addChildIds: [childId] });
    if (!result.ok) {
      return jsonResponse(
        { ok: false, error: result.error || "failed to update parent tag relation", detail: result.detail || null },
        500,
      );
    }
    parentUpdated = result.tag;
  }

  return okResponse({
    parent: parentUpdated || { id: parentId, children: [] },
    child: childUpdated.tag,
  });
}

async function handleR2Upload(request, env) {
  if (!env.GALLERY_R2) return serverError("R2 binding not configured (GALLERY_R2)");
  const baseUrl = getEnvString(env, "R2_PUBLIC_BASE_URL");
  if (!baseUrl) return serverError("R2_PUBLIC_BASE_URL not configured");

  let form;
  try {
    form = await request.formData();
  } catch {
    return badRequest("invalid form-data");
  }

  const files = form.getAll("files");
  if (!files || files.length === 0) return badRequest("no files");

  const prefix = asString(form.get("prefix")).trim() || "uploads";

  const results = [];
  for (const f of files) {
    if (!(f instanceof File)) continue;
    const contentType = asString(f.type) || "application/octet-stream";
    const extFromName = (() => {
      const name = asString(f.name);
      const idx = name.lastIndexOf(".");
      if (idx === -1) return "";
      return name.slice(idx).toLowerCase();
    })();
    const ext = extFromName || (contentType === "image/jpeg" ? ".jpg" : contentType === "image/png" ? ".png" : "");
    const key = `${prefix}/${crypto.randomUUID()}${ext}`;

    await env.GALLERY_R2.put(key, f.stream(), {
      httpMetadata: {
        contentType,
        cacheControl: "public, max-age=31536000, immutable",
      },
    });

    const url = `${baseUrl.replace(/\/$/, "")}/${key}`;
    results.push({ key, url, name: asString(f.name) || key.split("/").pop(), type: contentType });
  }

  return okResponse({ files: results });
}

async function handleR2Delete(request, env) {
  if (!env.GALLERY_R2) return serverError("R2 binding not configured (GALLERY_R2)");
  const payload = await readJson(request);
  if (!payload || typeof payload !== "object") return badRequest("invalid json");
  const keys = Array.isArray(payload.keys) ? payload.keys.map((k) => asString(k).trim()).filter(Boolean) : [];
  if (keys.length === 0) return badRequest("no keys");

  await Promise.all(keys.map((k) => env.GALLERY_R2.delete(k)));
  return okResponse({ deleted: keys.length });
}

async function fetchWorkPage(env, workId) {
  const res = await notionFetch(env, `/pages/${workId}`, { method: "GET" });
  if (!res.ok) return null;
  return res.data;
}

async function handleImageSplit(request, env) {
  const worksDbId = getEnvString(env, "NOTION_WORKS_DB_ID");
  if (!worksDbId) return serverError("NOTION_WORKS_DB_ID not configured");
  const worksProps = getWorksProps(env);

  const payload = await readJson(request);
  if (!payload || typeof payload !== "object") return badRequest("invalid json");

  const sourceWorkId = asString(payload.sourceWorkId).trim();
  const imageUrls = Array.isArray(payload.imageUrls) ? payload.imageUrls.map((u) => asString(u).trim()).filter(Boolean) : [];
  if (!sourceWorkId || imageUrls.length === 0) return badRequest("missing params");

  const sourcePage = await fetchWorkPage(env, sourceWorkId);
  if (!sourcePage) return jsonResponse({ ok: false, error: "source work not found" }, 404);

  const source = simplifyWorkFromNotionPage(env, sourcePage);
  const selected = source.images.filter((img) => imageUrls.includes(img.url));
  if (selected.length === 0) return badRequest("no matching images");
  const remaining = source.images.filter((img) => !imageUrls.includes(img.url));

  const createPayload = {
    title: source.title,
    completedDate: source.completedDate,
    classroom: source.classroom,
    venue: source.venue,
    authorIds: source.authorIds,
    tagIds: source.tagIds,
    caption: source.caption,
    ready: false,
    images: selected,
  };

  const createRes = await notionFetch(env, "/pages", {
    method: "POST",
    body: JSON.stringify({
      parent: { database_id: worksDbId },
      properties: pickWorkProperties(env, createPayload),
    }),
  });
  if (!createRes.ok) {
    return jsonResponse({ ok: false, error: "failed to create split work", detail: createRes.data }, 500);
  }

  const updateRes = await notionFetch(env, `/pages/${sourceWorkId}`, {
    method: "PATCH",
    body: JSON.stringify({
      properties: {
        [worksProps.images || "画像"]: notionExternalFiles(remaining),
      },
    }),
  });
  if (!updateRes.ok) {
    return jsonResponse(
      { ok: false, error: "split created but failed to update source images", newWorkId: asString(createRes.data?.id), detail: updateRes.data },
      500,
    );
  }

  return okResponse({ newWorkId: asString(createRes.data?.id), remainingCount: remaining.length });
}

async function handleImageMove(request, env) {
  const worksProps = getWorksProps(env);

  const payload = await readJson(request);
  if (!payload || typeof payload !== "object") return badRequest("invalid json");

  const sourceWorkId = asString(payload.sourceWorkId).trim();
  const targetWorkId = asString(payload.targetWorkId).trim();
  const imageUrls = Array.isArray(payload.imageUrls) ? payload.imageUrls.map((u) => asString(u).trim()).filter(Boolean) : [];
  const archiveSourceIfEmpty = payload.archiveSourceIfEmpty !== false;

  if (!sourceWorkId || !targetWorkId || imageUrls.length === 0) return badRequest("missing params");

  const [sourcePage, targetPage] = await Promise.all([fetchWorkPage(env, sourceWorkId), fetchWorkPage(env, targetWorkId)]);
  if (!sourcePage) return jsonResponse({ ok: false, error: "source work not found" }, 404);
  if (!targetPage) return jsonResponse({ ok: false, error: "target work not found" }, 404);

  const source = simplifyWorkFromNotionPage(env, sourcePage);
  const target = simplifyWorkFromNotionPage(env, targetPage);

  const moving = source.images.filter((img) => imageUrls.includes(img.url));
  if (moving.length === 0) return badRequest("no matching images");

  const remaining = source.images.filter((img) => !imageUrls.includes(img.url));
  const nextTargetImages = [...target.images, ...moving];

  const updateTarget = notionFetch(env, `/pages/${targetWorkId}`, {
    method: "PATCH",
    body: JSON.stringify({
      properties: {
        [worksProps.images || "画像"]: notionExternalFiles(nextTargetImages),
      },
    }),
  });

  const updateSource = notionFetch(env, `/pages/${sourceWorkId}`, {
    method: "PATCH",
    body: JSON.stringify({
      properties: {
        [worksProps.images || "画像"]: notionExternalFiles(remaining),
      },
    }),
  });

  const [targetRes, sourceRes] = await Promise.all([updateTarget, updateSource]);
  if (!targetRes.ok || !sourceRes.ok) {
    return jsonResponse(
      { ok: false, error: "failed to move images", detail: { target: targetRes.data, source: sourceRes.data } },
      500,
    );
  }

  if (archiveSourceIfEmpty && remaining.length === 0) {
    await notionFetch(env, `/pages/${sourceWorkId}`, {
      method: "PATCH",
      body: JSON.stringify({ archived: true }),
    });
  }

  return okResponse({ moved: moving.length, sourceRemaining: remaining.length });
}

async function handleImageMerge(request, env) {
  const worksProps = getWorksProps(env);

  const payload = await readJson(request);
  if (!payload || typeof payload !== "object") return badRequest("invalid json");

  const targetWorkId = asString(payload.targetWorkId).trim();
  const sourceWorkIds = Array.isArray(payload.sourceWorkIds)
    ? payload.sourceWorkIds.map((id) => asString(id).trim()).filter(Boolean)
    : [];
  const archiveSources = payload.archiveSources !== false;

  if (!targetWorkId || sourceWorkIds.length === 0) return badRequest("missing params");

  const targetPage = await fetchWorkPage(env, targetWorkId);
  if (!targetPage) return jsonResponse({ ok: false, error: "target work not found" }, 404);
  const target = simplifyWorkFromNotionPage(env, targetPage);

  const sourcePages = await Promise.all(sourceWorkIds.map((id) => fetchWorkPage(env, id)));
  const sources = sourcePages
    .map((p, idx) => (p ? { id: sourceWorkIds[idx], work: simplifyWorkFromNotionPage(env, p) } : null))
    .filter(Boolean);
  if (sources.length === 0) return badRequest("no valid sources");

  const nextImages = [...target.images];
  const seen = new Set(nextImages.map((img) => img.url));
  for (const { work } of sources) {
    for (const img of work.images) {
      if (seen.has(img.url)) continue;
      seen.add(img.url);
      nextImages.push(img);
    }
  }

  const updateRes = await notionFetch(env, `/pages/${targetWorkId}`, {
    method: "PATCH",
    body: JSON.stringify({
      properties: {
        [worksProps.images || "画像"]: notionExternalFiles(nextImages),
      },
    }),
  });

  if (!updateRes.ok) {
    return jsonResponse({ ok: false, error: "failed to update target images", detail: updateRes.data }, 500);
  }

  if (archiveSources) {
    await Promise.all(
      sources.map(({ id }) =>
        notionFetch(env, `/pages/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ archived: true }),
        }),
      ),
    );
  }

  return okResponse({ mergedSources: sources.length, targetImageCount: nextImages.length });
}

function buildTagRecalcOptions(payload, env) {
  const dryRun = Boolean(payload?.dryRun) || payload?.apply === false;
  const apply = !dryRun;
  const requestedMaxUpdates = Number(payload?.maxUpdates);
  const configuredMaxUpdates = Number(getEnvString(env, "TAG_RECALC_MAX_UPDATES", "120"));
  const fallbackMaxUpdates = Number.isFinite(configuredMaxUpdates) && configuredMaxUpdates > 0 ? Math.floor(configuredMaxUpdates) : 120;
  const maxUpdates =
    Number.isFinite(requestedMaxUpdates) && requestedMaxUpdates > 0
      ? Math.floor(requestedMaxUpdates)
      : apply
        ? fallbackMaxUpdates
        : 0;

  return {
    dryRun,
    apply,
    maxUpdates,
    from: normalizeYmd(payload?.from),
    to: normalizeYmd(payload?.to),
    tagId: asString(payload?.tagId).trim(),
    unpreparedOnly: Boolean(payload?.unpreparedOnly),
  };
}

function resolveTagRecalcPropertyNames(env, worksDb, tagsDb) {
  const worksProps = getWorksProps(env);
  const worksTitleProp = pickPropertyName(worksDb, [worksProps.title, "作品名"], "title");
  const worksTagsProp = pickPropertyName(worksDb, [worksProps.tags, "タグ"], "relation");
  const worksReadyProp = pickPropertyName(worksDb, [worksProps.ready, "整備済み", "整備済"], "");
  const worksCompletedProp = pickPropertyName(worksDb, [worksProps.completedDate, "完成日"], "date");

  const tagTitleProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_TITLE_PROP", "タグ"), "タグ", "タグ名"], "title");
  const tagStatusProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_STATUS_PROP", "状態"), "状態"], "");
  const tagMergeToProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_MERGE_TO_PROP", "統合先"), "統合先"], "");
  const tagParentsProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_PARENTS_PROP", "親タグ"), "親タグ"], "");

  return {
    worksTitleProp,
    worksTagsProp,
    worksReadyProp,
    worksCompletedProp,
    tagTitleProp,
    tagStatusProp,
    tagMergeToProp,
    tagParentsProp,
  };
}

function buildTagRecalcMetadata(tagPages, tagProps) {
  const tagById = new Map();
  for (const page of tagPages) {
    const id = asString(page?.id).trim();
    if (!id) continue;
    const name = extractPropertyText(getPageProperty(page, tagProps.tagTitleProp)).trim();
    const status = normalizeTagStatus(extractPropertyText(getPageProperty(page, tagProps.tagStatusProp)));
    const mergeTo = tagProps.tagMergeToProp ? extractRelationIds(getPageProperty(page, tagProps.tagMergeToProp))[0] || "" : "";
    const parents = tagProps.tagParentsProp ? extractRelationIds(getPageProperty(page, tagProps.tagParentsProp)) : [];
    tagById.set(id, { id, name, status, mergeTo, parents });
  }

  const resolveMerge = buildMergeResolver(tagById);
  const warnings = [];
  const cycles = detectParentCycles(tagById, resolveMerge);
  if (cycles.length > 0) {
    warnings.push(`親子関係に循環が疑われます（例: ${cycles[0].join(" -> ")}）`);
  }

  let mergedIssueCount = 0;
  for (const tag of tagById.values()) {
    if (tag.status !== "merged") continue;
    const mergeTo = asString(tag.mergeTo).trim();
    if (!mergeTo) {
      mergedIssueCount += 1;
      if (warnings.length < 5) warnings.push(`mergedだが統合先が空: ${tag.id}`);
      continue;
    }
    if (!tagById.has(mergeTo)) {
      mergedIssueCount += 1;
      if (warnings.length < 5) warnings.push(`統合先が存在しない: ${tag.id} -> ${mergeTo}`);
    }
  }
  if (mergedIssueCount > 5) {
    warnings.push(`merged整合性の警告が他${mergedIssueCount - 5}件あります`);
  }

  return { tagById, resolveMerge, warnings, cycles };
}

function buildTagRecalcWorksQueryBody(options, worksProps) {
  const filters = [];
  if (options.unpreparedOnly && worksProps.worksReadyProp) {
    filters.push({ property: worksProps.worksReadyProp, checkbox: { equals: false } });
  }
  if (options.tagId) {
    filters.push({ property: worksProps.worksTagsProp, relation: { contains: options.tagId } });
  }
  if (options.from && worksProps.worksCompletedProp) {
    filters.push({ property: worksProps.worksCompletedProp, date: { on_or_after: options.from } });
  }
  if (options.to && worksProps.worksCompletedProp) {
    filters.push({ property: worksProps.worksCompletedProp, date: { on_or_before: options.to } });
  }

  const body = {};
  if (worksProps.worksCompletedProp) {
    body.sorts = [{ property: worksProps.worksCompletedProp, direction: "descending" }];
  }
  if (filters.length === 1) body.filter = filters[0];
  if (filters.length > 1) body.filter = { and: filters };
  return body;
}

function collectTagRecalcChanges(workPages, worksProps, tagMeta) {
  const changes = [];
  for (const page of workPages) {
    const id = asString(page?.id).trim();
    if (!id) continue;

    const currentTagIds = uniqueIds(extractRelationIds(getPageProperty(page, worksProps.worksTagsProp)));
    const normalizedSet = new Set();
    for (const tagValue of currentTagIds) {
      const resolved = tagMeta.resolveMerge(tagValue);
      if (resolved) normalizedSet.add(resolved);
    }

    const ancestorIds = computeAncestorTagIds(Array.from(normalizedSet), tagMeta.tagById, tagMeta.resolveMerge);
    for (const ancestorId of ancestorIds) normalizedSet.add(ancestorId);

    const nextTagIds = Array.from(normalizedSet);
    if (isSameIdSet(currentTagIds, nextTagIds)) continue;

    changes.push({
      id,
      title: worksProps.worksTitleProp ? extractPropertyText(getPageProperty(page, worksProps.worksTitleProp)).trim() : "",
      completedDate: worksProps.worksCompletedProp ? asString(getPageProperty(page, worksProps.worksCompletedProp)?.date?.start).trim() : "",
      before: currentTagIds,
      after: nextTagIds,
    });
  }
  return changes;
}

async function applyTagRecalcChanges(env, changes, worksTagsProp, maxUpdates) {
  let updated = 0;
  for (const change of changes) {
    if (maxUpdates > 0 && updated >= maxUpdates) break;

    const patchRes = await notionFetch(env, `/pages/${change.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        properties: {
          [worksTagsProp]: notionRelation(change.after),
        },
      }),
    });
    if (!patchRes.ok) {
      return {
        ok: false,
        updated,
        failed_id: change.id,
        detail: patchRes.data,
      };
    }

    updated += 1;
    if (updated < changes.length && (!maxUpdates || updated < maxUpdates)) {
      await sleep(350);
    }
  }

  return { ok: true, updated };
}

async function handleTagRecalc(request, env) {
  const worksDbId = getEnvString(env, "NOTION_WORKS_DB_ID");
  const tagsDbId = getEnvString(env, "NOTION_TAGS_DB_ID");
  if (!worksDbId) return serverError("NOTION_WORKS_DB_ID not configured");
  if (!tagsDbId) return serverError("NOTION_TAGS_DB_ID not configured");

  const payloadRaw = await readJson(request);
  if (payloadRaw !== null && (typeof payloadRaw !== "object" || Array.isArray(payloadRaw))) {
    return badRequest("invalid json");
  }
  const payload = payloadRaw && typeof payloadRaw === "object" ? payloadRaw : {};
  const options = buildTagRecalcOptions(payload, env);

  const [worksDbRes, tagsDbRes] = await Promise.all([
    notionFetch(env, `/databases/${worksDbId}`, { method: "GET" }),
    notionFetch(env, `/databases/${tagsDbId}`, { method: "GET" }),
  ]);

  if (!worksDbRes.ok) {
    return jsonResponse({ ok: false, error: "failed to fetch works database", detail: worksDbRes.data }, 500);
  }
  if (!tagsDbRes.ok) {
    return jsonResponse({ ok: false, error: "failed to fetch tags database", detail: tagsDbRes.data }, 500);
  }

  const worksDb = worksDbRes.data;
  const tagsDb = tagsDbRes.data;
  const propNames = resolveTagRecalcPropertyNames(env, worksDb, tagsDb);
  if (!propNames.worksTagsProp) return serverError("works tags relation property not found");
  if (!propNames.tagTitleProp) return serverError("tag title property not found");

  const tagsQueryRes = await queryAllDatabasePages(env, tagsDbId);
  if (!tagsQueryRes.ok) {
    return jsonResponse({ ok: false, error: "failed to query tags database", detail: tagsQueryRes.data }, 500);
  }
  const tagMeta = buildTagRecalcMetadata(tagsQueryRes.pages, propNames);

  const worksQueryBody = buildTagRecalcWorksQueryBody(options, propNames);

  const worksQueryRes = await queryAllDatabasePages(env, worksDbId, worksQueryBody);
  if (!worksQueryRes.ok) {
    return jsonResponse({ ok: false, error: "failed to query works database", detail: worksQueryRes.data }, 500);
  }
  const changes = collectTagRecalcChanges(worksQueryRes.pages, propNames, tagMeta);

  let updated = 0;
  if (options.apply) {
    const applyResult = await applyTagRecalcChanges(env, changes, propNames.worksTagsProp, options.maxUpdates);
    if (!applyResult.ok) {
      return jsonResponse(
        {
          ok: false,
          error: "failed to update work tags",
          updated: applyResult.updated,
          failed_id: applyResult.failed_id,
          detail: applyResult.detail,
        },
        500,
      );
    }
    updated = applyResult.updated;
  }

  const remaining = Math.max(0, changes.length - updated);
  return okResponse({
    dryRun: !options.apply,
    scanned: worksQueryRes.pages.length,
    changed: changes.length,
    updated,
    remaining,
    maxUpdates: options.apply ? options.maxUpdates : 0,
    warnings: tagMeta.warnings,
    cycles: tagMeta.cycles.length,
    samples: changes.slice(0, 10).map((change) => ({
      id: change.id,
      title: change.title,
      completedDate: change.completedDate,
      beforeCount: change.before.length,
      afterCount: change.after.length,
    })),
  });
}

async function handleTriggerGalleryUpdate(request, env) {
  const repo = getEnvString(env, "GITHUB_REPO");
  const token = getEnvString(env, "GITHUB_TOKEN");
  const workflowFile = getEnvString(env, "GITHUB_WORKFLOW_FILE", "gallery-export.yml");
  const ref = getEnvString(env, "GITHUB_REF", "main");

  if (!repo || !token) return serverError("GitHub env not configured (GITHUB_REPO, GITHUB_TOKEN)");

  const response = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/${workflowFile}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "gallery-admin",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref }),
  });

  if (response.status === 204) {
    return okResponse({ message: "workflow triggered" });
  }

  const text = await response.text().catch(() => "");
  return jsonResponse({ ok: false, error: `GitHub API error: ${text}` }, 500);
}

async function handleTriggerTagsIndexUpdate(request, env) {
  const tagsDbId = getEnvString(env, "NOTION_TAGS_DB_ID");
  if (!env.GALLERY_R2) return serverError("R2 binding not configured (GALLERY_R2)");
  if (!tagsDbId) return serverError("NOTION_TAGS_DB_ID not configured");

  const tagsDbRes = await notionFetch(env, `/databases/${tagsDbId}`, { method: "GET" });
  if (!tagsDbRes.ok) {
    return jsonResponse({ ok: false, error: "failed to fetch tags database", detail: tagsDbRes.data }, 500);
  }

  const queryRes = await queryAllDatabasePages(env, tagsDbId);
  if (!queryRes.ok) {
    return jsonResponse({ ok: false, error: "failed to query tags database", detail: queryRes.data }, 500);
  }

  const index = buildTagsIndexFromNotion(env, tagsDbId, tagsDbRes.data, queryRes.pages);
  const key = getEnvString(env, "TAGS_INDEX_KEY", "tags_index.json");
  const json = JSON.stringify(index);
  await env.GALLERY_R2.put(key, json, {
    httpMetadata: {
      contentType: "application/json; charset=utf-8",
      cacheControl: "max-age=300",
    },
  });

  return okResponse({
    message: "tags index regenerated",
    key,
    count: index.tags.length,
    generated_at: index.generated_at,
  });
}

async function handleProxyJson(env, urlVarName, r2KeyVarName, defaultKey) {
  const url = getEnvString(env, urlVarName);
  if (url) {
    const res = await fetch(url, { method: "GET" });
    if (!res.ok) return jsonResponse({ ok: false, error: "failed to fetch upstream json" }, 502);
    const data = await res.json().catch(() => null);
    if (!data) return jsonResponse({ ok: false, error: "invalid upstream json" }, 502);
    return okResponse({ data });
  }

  if (!env.GALLERY_R2) return serverError("R2 binding not configured (GALLERY_R2)");
  const key = getEnvString(env, r2KeyVarName, defaultKey);
  const obj = await env.GALLERY_R2.get(key);
  if (!obj) return jsonResponse({ ok: false, error: "not found" }, 404);
  const text = await obj.text();
  try {
    const data = JSON.parse(text);
    return okResponse({ data });
  } catch {
    return jsonResponse({ ok: false, error: "invalid json in r2" }, 502);
  }
}

async function handleParticipantsIndexPush(request, env) {
  if (!env.GALLERY_R2) return serverError("R2 binding not configured (GALLERY_R2)");

  const expectedToken =
    getEnvString(env, "UPLOAD_UI_PARTICIPANTS_INDEX_PUSH_TOKEN") ||
    getEnvString(env, "PARTICIPANTS_INDEX_PUSH_TOKEN");
  if (!expectedToken) {
    return serverError("UPLOAD_UI_PARTICIPANTS_INDEX_PUSH_TOKEN not configured");
  }

  const actualToken = getBearerToken(request);
  if (!actualToken || actualToken !== expectedToken) {
    return jsonResponse({ ok: false, error: "unauthorized" }, 401);
  }

  const payload = await readJson(request);
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return badRequest("invalid json");
  }

  const key = getEnvString(env, "PARTICIPANTS_INDEX_KEY", "participants_index.json");
  const json = JSON.stringify(payload);
  await env.GALLERY_R2.put(key, json, {
    httpMetadata: {
      contentType: "application/json; charset=utf-8",
      cacheControl: "max-age=300",
    },
  });

  return okResponse({
    key,
    bytes: new TextEncoder().encode(json).length,
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const { pathname } = url;

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: withCors() });
    }

    if (pathname === "/stars" && request.method === "GET") {
      return handleGetStars(url, env);
    }

    if (pathname === "/star" && request.method === "POST") {
      return handlePostStar(request, env);
    }

    if (pathname === "/participants-index" && request.method === "GET") {
      return handleProxyJson(env, "PARTICIPANTS_INDEX_URL", "PARTICIPANTS_INDEX_KEY", "participants_index.json");
    }

    if (pathname === "/participants-index" && request.method === "POST") {
      return handleParticipantsIndexPush(request, env);
    }

    if (pathname === "/students-index" && request.method === "GET") {
      return handleProxyJson(env, "STUDENTS_INDEX_URL", "STUDENTS_INDEX_KEY", "students_index.json");
    }

    if (pathname === "/tags-index" && request.method === "GET") {
      return handleProxyJson(env, "TAGS_INDEX_URL", "TAGS_INDEX_KEY", "tags_index.json");
    }

    if (pathname.startsWith("/admin/")) {
      const authError = requireAdminAuthorization(request, env);
      if (authError) return authError;
    }

    if (pathname === "/admin/notion/schema" && request.method === "GET") {
      return handleNotionSchema(env);
    }

    if (pathname === "/admin/notion/works" && request.method === "GET") {
      return handleNotionListWorks(url, env);
    }

    if (pathname === "/admin/notion/search-students" && request.method === "GET") {
      return handleNotionSearchStudents(url, env);
    }

    if (pathname === "/admin/notion/work" && request.method === "POST") {
      return handleNotionCreateWork(request, env);
    }

    if (pathname === "/admin/notion/work" && request.method === "PATCH") {
      return handleNotionUpdateWork(request, env);
    }

    if (pathname === "/admin/notion/tag" && request.method === "POST") {
      return handleNotionCreateTag(request, env);
    }

    if (pathname === "/admin/notion/tag" && request.method === "PATCH") {
      return handleNotionUpdateTag(request, env);
    }

    if (pathname === "/admin/r2/upload" && request.method === "POST") {
      return handleR2Upload(request, env);
    }

    if (pathname === "/admin/r2/delete" && request.method === "POST") {
      return handleR2Delete(request, env);
    }

    if (pathname === "/admin/image/split" && request.method === "POST") {
      return handleImageSplit(request, env);
    }

    if (pathname === "/admin/image/move" && request.method === "POST") {
      return handleImageMove(request, env);
    }

    if (pathname === "/admin/image/merge" && request.method === "POST") {
      return handleImageMerge(request, env);
    }

    if (pathname === "/admin/trigger-gallery-update" && request.method === "POST") {
      return handleTriggerGalleryUpdate(request, env);
    }

    if (pathname === "/admin/trigger-tags-index-update" && request.method === "POST") {
      return handleTriggerTagsIndexUpdate(request, env);
    }

    if (pathname === "/admin/tag-recalc" && request.method === "POST") {
      return handleTagRecalc(request, env);
    }

    return new Response("Not found", {
      status: 404,
      headers: withCors({ "Cache-Control": "no-store" }),
    });
  },
};
