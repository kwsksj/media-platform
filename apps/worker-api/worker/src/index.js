const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Access-Control-Max-Age": "86400",
};
const UPLOAD_NOTIFY_PENDING_WORK_PREFIX = "upload_notify:pending:work:";
const UPLOAD_NOTIFY_STATUS_WORK_PREFIX = "upload_notify:status:work:";
const UPLOAD_NOTIFY_DISABLED_WORK_PREFIX = "upload_notify:disabled:work:";

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

function getEnvInteger(env, key, fallback, { min = Number.MIN_SAFE_INTEGER, max = Number.MAX_SAFE_INTEGER } = {}) {
  const raw = getEnvString(env, key, "");
  if (!raw) return fallback;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return fallback;
  const value = Math.floor(parsed);
  if (value < min || value > max) return fallback;
  return value;
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
  if (type === "email") return asString(prop.email).trim();
  if (type === "phone_number") return asString(prop.phone_number).trim();
  if (type === "url") return asString(prop.url).trim();
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

function toHiragana(value) {
  const input = asString(value);
  let out = "";
  for (const ch of input) {
    const code = ch.charCodeAt(0);
    if (code >= 0x30a1 && code <= 0x30f6) {
      out += String.fromCharCode(code - 0x60);
    } else {
      out += ch;
    }
  }
  return out;
}

function normalizeTagNameKey(value) {
  return toHiragana(asString(value).toLowerCase().trim());
}

function normalizeTagAliasValues(raw) {
  const inputs = Array.isArray(raw) ? raw : [raw];
  const out = [];
  const seen = new Set();
  for (const source of inputs) {
    const aliases = splitAliases(asString(source));
    for (const aliasRaw of aliases) {
      const alias = asString(aliasRaw).trim();
      const key = normalizeTagNameKey(alias);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(alias);
    }
  }
  return out;
}

function findExistingTagByNameOrAlias(tags, names) {
  const candidates = Array.isArray(names) ? names : [names];
  const keys = new Set(candidates.map((value) => normalizeTagNameKey(value)).filter(Boolean));
  if (keys.size === 0) return null;

  for (const tag of Array.isArray(tags) ? tags : []) {
    const values = [tag?.name, ...(Array.isArray(tag?.aliases) ? tag.aliases : [])];
    for (const value of values) {
      if (keys.has(normalizeTagNameKey(value))) return tag;
    }
  }
  return null;
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

function isTruthyString(value) {
  const v = asString(value).trim().toLowerCase();
  if (!v) return false;
  return ["1", "true", "yes", "y", "on", "enabled"].includes(v);
}

function isFalsyString(value) {
  const v = asString(value).trim().toLowerCase();
  if (!v) return false;
  return ["0", "false", "no", "n", "off", "disabled"].includes(v);
}

function isLikelyEmail(value) {
  const email = asString(value).trim();
  if (!email) return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/u.test(email);
}

function extractEmailCandidate(value) {
  const raw = asString(value).trim();
  if (!raw) return "";
  const match = raw.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/iu);
  return match ? asString(match[0]).trim() : "";
}

function parseEmailList(value) {
  const raw = asString(value).trim();
  if (!raw) return [];
  const out = [];
  const seen = new Set();
  for (const part of raw.split(/[,\s;、，；]+/u)) {
    const email = asString(part).trim();
    if (!isLikelyEmail(email)) continue;
    const key = email.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(email);
  }
  return out;
}

function extractPropertyEmail(prop) {
  if (!prop || typeof prop !== "object") return "";
  if (prop.type === "email") {
    const email = asString(prop.email).trim();
    return isLikelyEmail(email) ? email : "";
  }
  if (prop.type === "rich_text") {
    const email = extractEmailCandidate(extractPlainTextItems(prop.rich_text));
    return isLikelyEmail(email) ? email : "";
  }
  if (prop.type === "formula") {
    const formula = prop.formula;
    if (formula?.type === "string") {
      const email = extractEmailCandidate(formula.string);
      return isLikelyEmail(email) ? email : "";
    }
  }
  const fallback = extractEmailCandidate(extractPropertyText(prop));
  return isLikelyEmail(fallback) ? fallback : "";
}

function extractBooleanLikeProperty(prop) {
  if (!prop || typeof prop !== "object") return null;
  if (prop.type === "checkbox") return Boolean(prop.checkbox);
  if (prop.type === "formula" && prop.formula?.type === "boolean") {
    return Boolean(prop.formula.boolean);
  }

  const text = extractPropertyText(prop).trim().toLowerCase();
  if (!text) return null;
  if (isTruthyString(text)) return true;
  if (isFalsyString(text)) return false;

  if (["希望", "希望する", "可", "許可", "ok", "あり", "有", "有効", "する"].includes(text)) {
    return true;
  }
  if (["不要", "希望しない", "不可", "非許可", "なし", "無", "無効", "しない"].includes(text)) {
    return false;
  }
  return null;
}

function resolveFromAddress(fromEmail, fromName) {
  const email = asString(fromEmail).trim();
  const name = asString(fromName).trim();
  if (!name) return email;
  const safeName = name.replaceAll('"', '\\"');
  return `"${safeName}" <${email}>`;
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

function notionMultiSelect(values) {
  if (!Array.isArray(values)) return { multi_select: [] };
  return {
    multi_select: values
      .map((value) => asString(value).trim())
      .filter(Boolean)
      .map((name) => ({ name })),
  };
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

async function resolveStudentsDbIdForNotifications(env) {
  const explicit = getEnvString(env, "NOTION_STUDENTS_DB_ID");
  if (explicit) return explicit;

  const worksDbId = getEnvString(env, "NOTION_WORKS_DB_ID");
  if (!worksDbId) return "";

  const worksDbRes = await notionFetch(env, `/databases/${worksDbId}`, { method: "GET" });
  if (!worksDbRes.ok) return "";

  const worksProps = getWorksProps(env);
  const authorPropName = pickPropertyName(
    worksDbRes.data,
    [worksProps.author, "作者", "生徒", "生徒名"],
    "",
  );
  if (!authorPropName) return "";
  const authorProp = worksDbRes.data?.properties?.[authorPropName];
  if (!authorProp || authorProp.type !== "relation") return "";
  return asString(authorProp?.relation?.database_id).trim();
}

async function collectStudentNotificationRecipients(env, authorIds) {
  const ids = uniqueIds(authorIds);
  if (ids.length === 0) {
    return {
      ok: true,
      recipients: [],
      skippedNoEmail: 0,
      skippedOptOut: 0,
      skippedNotFound: 0,
      reason: "no_authors",
      terminalSkippedAuthorIds: [],
    };
  }

  const studentsDbId = await resolveStudentsDbIdForNotifications(env);
  if (!studentsDbId) {
    return {
      ok: false,
      recipients: [],
      skippedNoEmail: 0,
      skippedOptOut: 0,
      skippedNotFound: ids.length,
      reason: "students_db_not_found",
      terminalSkippedAuthorIds: [],
    };
  }

  const studentsDbRes = await notionFetch(env, `/databases/${studentsDbId}`, { method: "GET" });
  if (!studentsDbRes.ok) {
    return {
      ok: false,
      recipients: [],
      skippedNoEmail: 0,
      skippedOptOut: 0,
      skippedNotFound: ids.length,
      reason: "students_db_fetch_failed",
      terminalSkippedAuthorIds: [],
    };
  }

  const studentsDb = studentsDbRes.data;
  const titleProp = findFirstDatabasePropertyNameByType(studentsDb, "title");
  const nicknameProp = studentsDb?.properties?.["ニックネーム"] ? "ニックネーム" : "";
  const realNameProp = studentsDb?.properties?.["本名"] ? "本名" : "";

  const emailOverride = getEnvString(env, "NOTION_STUDENTS_EMAIL_PROP");
  const emailPreferred = emailOverride
    ? [emailOverride]
    : ["メールアドレス", "メール", "Email", "email"];
  const emailProp = pickPropertyName(studentsDb, emailPreferred, "email");

  const notifyOptInOverride = getEnvString(env, "NOTION_STUDENTS_NOTIFY_OPT_IN_PROP");
  // Do not infer opt-in property by default.
  // Reservation/schedule preference fields are often unrelated to gallery upload notifications.
  const notifyOptInProp = notifyOptInOverride
    ? pickPropertyName(studentsDb, [notifyOptInOverride], "")
    : "";

  let skippedNoEmail = 0;
  let skippedOptOut = 0;
  let skippedNotFound = 0;
  let retryableFetchErrors = 0;
  const recipients = [];
  const terminalSkippedAuthorIdSet = new Set();

  const pageResults = await Promise.all(
    ids.map(async (id) => {
      const res = await notionFetch(env, `/pages/${id}`, { method: "GET" });
      return { id, res };
    }),
  );

  for (const entry of pageResults) {
    if (!entry.res.ok) {
      if (Number(entry.res.status) === 404) {
        skippedNotFound += 1;
        terminalSkippedAuthorIdSet.add(entry.id);
      } else {
        retryableFetchErrors += 1;
      }
      continue;
    }

    const page = entry.res.data;
    if (notifyOptInProp) {
      const optInValue = extractBooleanLikeProperty(getPageProperty(page, notifyOptInProp));
      if (optInValue === false) {
        skippedOptOut += 1;
        terminalSkippedAuthorIdSet.add(entry.id);
        continue;
      }
    }

    let email = emailProp ? extractPropertyEmail(getPageProperty(page, emailProp)) : "";
    if (!email) {
      const props = page?.properties || {};
      for (const prop of Object.values(props)) {
        email = extractPropertyEmail(prop);
        if (email) break;
      }
    }
    if (!email) {
      skippedNoEmail += 1;
      terminalSkippedAuthorIdSet.add(entry.id);
      continue;
    }

    const title = titleProp ? extractPropertyText(getPageProperty(page, titleProp)).trim() : "";
    const parsed = splitStudentNameLabel(title);
    const realName = (realNameProp ? extractPropertyText(getPageProperty(page, realNameProp)) : "").trim() || parsed.realName;
    const nicknameRaw =
      (nicknameProp ? extractPropertyText(getPageProperty(page, nicknameProp)) : "").trim() ||
      parsed.nickname ||
      title;
    const nickname = normalizeNickname(nicknameRaw, realName) || parsed.nickname || realName;
    const name = nickname || realName || "生徒さま";

    recipients.push({
      authorIds: [entry.id],
      email: email.toLowerCase(),
      name,
    });
  }

  if (retryableFetchErrors > 0) {
    return {
      ok: false,
      recipients: [],
      skippedNoEmail,
      skippedOptOut,
      skippedNotFound,
      reason: "students_page_fetch_failed",
      terminalSkippedAuthorIds: [],
    };
  }

  const deduped = [];
  const recipientByEmail = new Map();
  for (const recipient of recipients) {
    const existing = recipientByEmail.get(recipient.email);
    if (!existing) {
      recipientByEmail.set(recipient.email, {
        authorIds: [...recipient.authorIds],
        email: recipient.email,
        name: recipient.name,
      });
      continue;
    }
    existing.authorIds = uniqueIds([...existing.authorIds, ...recipient.authorIds]);
  }
  deduped.push(...recipientByEmail.values());

  return {
    ok: true,
    recipients: deduped,
    skippedNoEmail,
    skippedOptOut,
    skippedNotFound,
    reason: "",
    terminalSkippedAuthorIds: Array.from(terminalSkippedAuthorIdSet.values()),
  };
}

function escapeHtml(value) {
  return asString(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function resolveUploadNotificationLinks(env) {
  const bookingUrl = getEnvString(env, "UPLOAD_NOTIFY_RESERVATION_APP_URL") || "https://www.kibori-class.net/booking";
  const publicGalleryUrl = getEnvString(env, "UPLOAD_NOTIFY_GALLERY_URL") || "https://www.kibori-class.net/students-gallery";
  return { bookingUrl, publicGalleryUrl };
}

function appendUploadNotificationGuideText(lines, links) {
  lines.push(
    "",
    "【ログインして見る】",
    "「よやく・きろく」ページでログイン後、【さくひんギャラリー】ボタンから、",
    "「ご自身の作品」と「みんなの作品」を分けて見られます。",
    links.bookingUrl,
    "",
    "【一般公開ページ（ログイン不要）】",
    "ログインなしで見られる生徒作品ページはこちらです。",
    links.publicGalleryUrl,
    "",
    "【表示名について】",
    "作品ギャラリーでの生徒表示名は、「よやく・きろく」ページのニックネーム設定を使います。",
    "ニックネーム未設定の場合は、一般公開ページではランダム名、登録生徒向けページでは登録名の頭文字２文字で表示されます。",
    "表示名を変更したい場合は、「よやく・きろく」ページでニックネームを設定してください。",
  );
}

function buildUploadNotificationGuideHtml(links) {
  return [
    `<p><strong>【ログインして見る】</strong><br>「よやく・きろく」ページでログイン後、【さくひんギャラリー】ボタンから、<br>「ご自身の作品」と「みんなの作品」を分けて見られます。<br><a href="${escapeHtml(links.bookingUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(links.bookingUrl)}</a></p>`,
    `<p><strong>【一般公開ページ（ログイン不要）】</strong><br>ログインなしで見られる生徒作品ページはこちらです。<br><a href="${escapeHtml(links.publicGalleryUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(links.publicGalleryUrl)}</a></p>`,
    "<p><strong>【表示名について】</strong><br>作品ギャラリーでの生徒表示名は、「よやく・きろく」ページのニックネーム設定を使います。<br>ニックネーム未設定の場合は、一般公開ページではランダム名、登録生徒向けページでは登録名の頭文字２文字で表示されます。<br>表示名を変更したい場合は、「よやく・きろく」ページでニックネームを設定してください。</p>",
  ].join("");
}

function appendUploadNotificationCountNoteText(lines) {
  lines.push(
    "",
    "【掲載件数について】",
    "1つの作品に複数の作者を設定したり、個別写真と集合写真を別々に登録することがあるため、",
    "掲載件数は実際の作品数と一致しない場合があります。",
  );
}

function buildUploadNotificationCountNoteHtml() {
  return "<p><strong>【掲載件数について】</strong><br>1つの作品に複数の作者を設定したり、個別写真と集合写真を別々に登録することがあるため、<br>掲載件数は実際の作品数と一致しない場合があります。</p>";
}

function buildRecipientSalutation(recipient) {
  let base = asString(recipient?.name).trim();
  if (base.endsWith("様")) {
    base = base.slice(0, -1).trim();
  }
  if (base.endsWith("さま")) {
    base = base.slice(0, -2).trim();
  }
  if (!base) base = "生徒";
  return `${base}さま`;
}

function buildUploadNotificationContent(env, payload, recipient) {
  const title = asString(payload?.title).trim() || "新しい作品";
  const completedDateRaw = normalizeYmd(payload?.completedDate) || asString(payload?.completedDate).trim();
  const classroomRaw = asString(payload?.classroom).trim();
  const imageCountRaw = Array.isArray(payload?.images) ? payload.images.length : 0;
  const completedDate = completedDateRaw || "-";
  const classroom = classroomRaw || "-";
  const imageCount = Number.isFinite(Number(imageCountRaw)) ? Math.max(0, Math.floor(Number(imageCountRaw))) : 0;
  const links = resolveUploadNotificationLinks(env);
  const subjectOverride = getEnvString(env, "UPLOAD_NOTIFY_SUBJECT");
  const subject = subjectOverride || `「${title}」を生徒作品ギャラリーに掲載しました！`;
  const salutation = buildRecipientSalutation(recipient);

  const lines = [
    salutation,
    "",
    "生徒作品ギャラリーに、あなたが作者として登録された作品写真を掲載しました！",
    "",
    `作品名: ${title}`,
    `完成日: ${completedDate}`,
    `教室: ${classroom}`,
    `枚数: ${imageCount}枚`,
  ];
  appendUploadNotificationGuideText(lines, links);
  appendUploadNotificationCountNoteText(lines);
  lines.push("", "このメールには返信できます。作品タイトルなどの変更希望があれば、このメールに返信してお知らせください。");
  const text = lines.join("\n");

  const htmlDetails = [
    `<li><strong>作品名:</strong> ${escapeHtml(title)}</li>`,
    `<li><strong>完成日:</strong> ${escapeHtml(completedDate)}</li>`,
    `<li><strong>教室:</strong> ${escapeHtml(classroom)}</li>`,
    `<li><strong>枚数:</strong> ${imageCount}枚</li>`,
  ];
  const html = [
		`<p>${escapeHtml(salutation)}</p>`,
		"<p>生徒作品ギャラリーに、あなたが作者として登録された作品写真を掲載しました！</p>",
		`<ul>${htmlDetails.join("")}</ul>`,
		"<p>このメールには返信できます。作品タイトルなどの変更希望があれば、このメールに返信してお知らせください。</p>",
		buildUploadNotificationGuideHtml(links),
		buildUploadNotificationCountNoteHtml(),
	].join("");

  return { subject, text, html };
}

function normalizeUploadBatchNotificationItems(itemsRaw) {
  if (!Array.isArray(itemsRaw)) return [];

  const normalized = [];
  const seen = new Set();
  for (const raw of itemsRaw) {
    const title = asString(raw?.title).trim();
    const completedDate = normalizeYmd(raw?.completedDate) || asString(raw?.completedDate).trim();
    const classroom = asString(raw?.classroom).trim();
    const workId = asString(raw?.workId).trim();
    const queuedAt = asString(raw?.queuedAt).trim();
    const imageCountRaw = Number(raw?.imageCount);
    const imageCount = Number.isFinite(imageCountRaw) ? Math.max(0, Math.floor(imageCountRaw)) : 0;
    const authorIdsRaw = uniqueIds(Array.isArray(raw?.authorIds) ? raw.authorIds : []);
    const pendingAuthorIdsRaw = uniqueIds(Array.isArray(raw?.pendingAuthorIds) ? raw.pendingAuthorIds : []);
    const authorIds = uniqueIds([...authorIdsRaw, ...pendingAuthorIdsRaw]);
    if (authorIds.length === 0) continue;
    const pendingAuthorIds = pendingAuthorIdsRaw.length > 0 ? [...pendingAuthorIdsRaw] : [...authorIds];
    if (pendingAuthorIds.length === 0) continue;
    const pendingAuthorIdsDerived = Boolean(raw?.pendingAuthorIdsDerived) || isSameIdSet(pendingAuthorIds, authorIds);

    const signature = `${workId}|${title}|${completedDate}|${classroom}|${imageCount}|${authorIds.join(",")}|${pendingAuthorIds.join(",")}`;
    if (seen.has(signature)) continue;
    seen.add(signature);

    normalized.push({
      title,
      completedDate,
      classroom,
      workId,
      queuedAt,
      imageCount,
      authorIds,
      pendingAuthorIds,
      pendingAuthorIdsDerived,
    });
  }
  return normalized;
}

function resolveAuthorIdsFromWorkPage(env, page) {
  const worksProps = getWorksProps(env);
  if (!worksProps.author) return [];
  const relation = page?.properties?.[worksProps.author]?.relation;
  if (!Array.isArray(relation)) return [];
  return uniqueIds(relation.map((entry) => asString(entry?.id)));
}

async function enrichUploadBatchWorksWithNotionAuthors(env, worksRaw) {
  if (!Array.isArray(worksRaw) || worksRaw.length === 0) return [];

  const works = worksRaw
    .map((work) => {
      const authorIds = uniqueIds(Array.isArray(work?.authorIds) ? work.authorIds : []);
      const pendingAuthorIdsRaw = uniqueIds(Array.isArray(work?.pendingAuthorIds) ? work.pendingAuthorIds : []);
      const mergedAuthorIds = uniqueIds([...authorIds, ...pendingAuthorIdsRaw]);
      if (mergedAuthorIds.length === 0) return null;
      const pendingAuthorIds =
        pendingAuthorIdsRaw.length > 0 ? pendingAuthorIdsRaw.filter((id) => mergedAuthorIds.includes(id)) : [...mergedAuthorIds];
      if (pendingAuthorIds.length === 0) return null;
      return {
        ...work,
        authorIds: mergedAuthorIds,
        pendingAuthorIds,
        pendingAuthorIdsDerived: Boolean(work?.pendingAuthorIdsDerived),
      };
    })
    .filter(Boolean);

  const targets = works.filter((work) => work.workId);
  const batchSize = 20;
  for (let offset = 0; offset < targets.length; offset += batchSize) {
    const batch = targets.slice(offset, offset + batchSize);
    const pages = await Promise.all(batch.map((work) => fetchWorkPage(env, work.workId)));
    for (let index = 0; index < batch.length; index += 1) {
      const work = batch[index];
      const previousAuthorIds = [...work.authorIds];
      const previousPendingAuthorIds = [...work.pendingAuthorIds];
      const resolvedAuthorIds = resolveAuthorIdsFromWorkPage(env, pages[index]);
      if (resolvedAuthorIds.length === 0) continue;
      work.authorIds = resolvedAuthorIds;
      const preservedPendingAuthorIds = previousPendingAuthorIds.filter((authorId) => resolvedAuthorIds.includes(authorId));
      const newlyAddedAuthorIds = resolvedAuthorIds.filter((authorId) => !previousAuthorIds.includes(authorId));
      work.pendingAuthorIds = uniqueIds([...preservedPendingAuthorIds, ...newlyAddedAuthorIds]);
    }
  }

  return works;
}

function buildUploadBatchNotificationContent(env, recipient, works) {
  const safeWorks = Array.isArray(works) ? works : [];
  if (safeWorks.length <= 1) {
    const first = safeWorks[0] || {};
    return buildUploadNotificationContent(
      env,
      {
        title: first.title,
        completedDate: first.completedDate,
        classroom: first.classroom,
        images: Array.from({ length: Math.max(0, Number(first.imageCount) || 0) }),
      },
      recipient,
    );
  }

  const salutation = buildRecipientSalutation(recipient);
  const links = resolveUploadNotificationLinks(env);
  const subjectOverride = getEnvString(env, "UPLOAD_NOTIFY_SUBJECT");
  const subject = subjectOverride || `生徒作品ギャラリーに${safeWorks.length}件の作品写真を掲載しました！`;

  const formatWorkLine = (work, index) => {
    const title = asString(work?.title).trim() || `作品${index + 1}`;
    const completedDate = asString(work?.completedDate).trim() || "-";
    const classroom = asString(work?.classroom).trim() || "-";
    const imageCount = Number.isFinite(Number(work?.imageCount)) ? Math.max(0, Math.floor(Number(work.imageCount))) : 0;
    return `- ${title}（${completedDate} / ${classroom} / ${imageCount}枚）`;
  };

  const lines = [
    salutation,
    "",
    "生徒作品ギャラリーに、あなたが作者として登録された作品写真を掲載しました！",
    `今回の掲載登録件数: ${safeWorks.length}件`,
    "",
    ...safeWorks.slice(0, 10).map((work, index) => formatWorkLine(work, index)),
  ];
  if (safeWorks.length > 10) lines.push(`- ほか ${safeWorks.length - 10}件`);
  appendUploadNotificationGuideText(lines, links);
  appendUploadNotificationCountNoteText(lines);
  lines.push("", "このメールには返信できます。作品タイトルなどの変更希望があれば、このメールに返信してお知らせください。");
  const text = lines.join("\n");

  const htmlWorkItems = safeWorks
    .slice(0, 10)
    .map((work, index) => {
      const title = escapeHtml(asString(work?.title).trim() || `作品${index + 1}`);
      const completedDate = escapeHtml(asString(work?.completedDate).trim() || "-");
      const classroom = escapeHtml(asString(work?.classroom).trim() || "-");
      const imageCount = Number.isFinite(Number(work?.imageCount)) ? Math.max(0, Math.floor(Number(work.imageCount))) : 0;
      return `<li>${title}（${completedDate} / ${classroom} / ${imageCount}枚）</li>`;
    });
  if (safeWorks.length > 10) {
    htmlWorkItems.push(`<li>ほか ${safeWorks.length - 10}件</li>`);
  }

  const html = [
    `<p>${escapeHtml(salutation)}</p>`,
    "<p>生徒作品ギャラリーに、あなたが作者として登録された作品写真を掲載しました！</p>",
    `<p>今回の掲載登録件数: ${safeWorks.length}件</p>`,
    `<ul>${htmlWorkItems.join("")}</ul>`,
    buildUploadNotificationGuideHtml(links),
    buildUploadNotificationCountNoteHtml(),
    "<p>このメールには返信できます。作品タイトルなどの変更希望があれば、このメールに返信してお知らせください。</p>",
  ].join("");

  return { subject, text, html };
}

function getUploadNotificationConfig(env) {
  const enabledRaw = getEnvString(env, "UPLOAD_NOTIFY_ENABLED");
  if (isFalsyString(enabledRaw)) {
    return { enabled: false, reason: "disabled", apiKey: "", from: "", replyTo: "", bcc: [] };
  }

  const apiKey = getEnvString(env, "UPLOAD_NOTIFY_RESEND_API_KEY");
  const fromEmail = getEnvString(env, "UPLOAD_NOTIFY_FROM_EMAIL");
  if (!apiKey || !fromEmail) {
    return { enabled: false, reason: "not_configured", apiKey: "", from: "", replyTo: "", bcc: [] };
  }
  if (!isLikelyEmail(fromEmail)) {
    return { enabled: false, reason: "invalid_from_email", apiKey: "", from: "", replyTo: "", bcc: [] };
  }

  const fromName = getEnvString(env, "UPLOAD_NOTIFY_FROM_NAME", "木彫り教室");
  const replyToRaw = getEnvString(env, "UPLOAD_NOTIFY_REPLY_TO");
  const replyTo = isLikelyEmail(replyToRaw) ? replyToRaw : "";
  const bcc = parseEmailList(getEnvString(env, "UPLOAD_NOTIFY_BCC"));
  const minIntervalMs = getEnvInteger(env, "UPLOAD_NOTIFY_RESEND_MIN_INTERVAL_MS", 1000, { min: 0, max: 60000 });
  const rateLimitRetryMs = getEnvInteger(env, "UPLOAD_NOTIFY_RESEND_RATE_LIMIT_RETRY_MS", 1500, { min: 250, max: 120000 });
  const rateLimitRetries = getEnvInteger(env, "UPLOAD_NOTIFY_RESEND_RATE_LIMIT_RETRIES", 2, { min: 0, max: 10 });

  return {
    enabled: true,
    reason: "",
    apiKey,
    from: resolveFromAddress(fromEmail, fromName),
    replyTo,
    bcc,
    minIntervalMs,
    rateLimitRetryMs,
    rateLimitRetries,
  };
}

function resolveRetryDelayMsFromResponse(response, fallbackMs = 1500) {
  const fallback = Number.isFinite(Number(fallbackMs))
    ? Math.max(250, Math.floor(Number(fallbackMs)))
    : 1500;

  const retryAfterRaw = asString(response?.headers?.get("retry-after")).trim();
  if (retryAfterRaw) {
    if (/^\d+(\.\d+)?$/.test(retryAfterRaw)) {
      const seconds = Number(retryAfterRaw);
      if (Number.isFinite(seconds) && seconds >= 0) {
        return Math.max(fallback, Math.ceil(seconds * 1000));
      }
    }
    const retryAt = Date.parse(retryAfterRaw);
    if (!Number.isNaN(retryAt)) {
      return Math.max(fallback, Math.max(0, retryAt - Date.now()));
    }
  }

  const rateResetRaw = asString(response?.headers?.get("x-ratelimit-reset")).trim();
  if (/^\d+(\.\d+)?$/.test(rateResetRaw)) {
    const resetSeconds = Number(rateResetRaw);
    if (Number.isFinite(resetSeconds) && resetSeconds > 0) {
      const waitMs = Math.ceil((resetSeconds - Date.now() / 1000) * 1000);
      if (waitMs > 0) return Math.max(fallback, waitMs);
    }
  }

  return fallback;
}

async function sendUploadNotificationWithResend(config, recipientEmail, content) {
  const payload = {
    from: config.from,
    to: [recipientEmail],
    subject: content.subject,
    text: content.text,
    html: content.html,
  };
  if (config.replyTo) payload.reply_to = config.replyTo;
  if (config.bcc.length > 0) payload.bcc = config.bcc;

  const rateLimitRetries = Number.isFinite(Number(config?.rateLimitRetries))
    ? Math.max(0, Math.floor(Number(config.rateLimitRetries)))
    : 0;
  const maxAttempts = rateLimitRetries + 1;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const response = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (response.ok) return;

    const detail = await response.text().catch(() => "");
    const shouldRetryRateLimit = response.status === 429 && attempt + 1 < maxAttempts;
    if (shouldRetryRateLimit) {
      const waitMs = resolveRetryDelayMsFromResponse(response, config?.rateLimitRetryMs);
      await sleep(waitMs);
      continue;
    }

    throw new Error(`resend_error:${response.status}${detail ? ` ${detail.slice(0, 240)}` : ""}`);
  }
}

function buildPendingWorkNotificationItem(workId, payload) {
  const authorIds = [
    ...(Array.isArray(payload?.authorIds) ? payload.authorIds : []),
    ...(payload?.authorId ? [payload.authorId] : []),
  ];
  const uniqueAuthorIds = uniqueIds(authorIds);
  const imageCount = Array.isArray(payload?.images) ? payload.images.length : 0;
  return {
    workId: asString(workId).trim(),
    title: asString(payload?.title).trim(),
    completedDate: normalizeYmd(payload?.completedDate) || asString(payload?.completedDate).trim(),
    classroom: asString(payload?.classroom).trim(),
    imageCount: Math.max(0, Number.isFinite(Number(imageCount)) ? Math.floor(Number(imageCount)) : 0),
    authorIds: uniqueAuthorIds,
    pendingAuthorIds: [...uniqueAuthorIds],
    queuedAt: new Date().toISOString(),
  };
}

function buildPendingWorkNotificationItemFromSnapshot(snapshot, pendingAuthorIdsRaw) {
  const workId = asString(snapshot?.workId).trim();
  const pendingAuthorIds = uniqueIds(Array.isArray(pendingAuthorIdsRaw) ? pendingAuthorIdsRaw : []);
  const authorIds = uniqueIds([...(Array.isArray(snapshot?.authorIds) ? snapshot.authorIds : []), ...pendingAuthorIds]);
  if (!workId || authorIds.length === 0 || pendingAuthorIds.length === 0) return null;

  const imageCount = Number(snapshot?.imageCount);
  return {
    workId,
    title: asString(snapshot?.title).trim(),
    completedDate: normalizeYmd(snapshot?.completedDate) || asString(snapshot?.completedDate).trim(),
    classroom: asString(snapshot?.classroom).trim(),
    imageCount: Number.isFinite(imageCount) ? Math.max(0, Math.floor(imageCount)) : 0,
    authorIds,
    pendingAuthorIds,
    queuedAt: asString(snapshot?.queuedAt).trim() || new Date().toISOString(),
  };
}

async function queuePendingWorkNotification(env, workId, payload) {
  if (!env.STAR_KV) return { queued: false, reason: "kv_not_configured" };

  const item = buildPendingWorkNotificationItem(workId, payload);
  if (!item.workId) return { queued: false, reason: "missing_work_id" };
  if (!Array.isArray(item.authorIds) || item.authorIds.length === 0) {
    return { queued: false, reason: "no_authors" };
  }

  const key = `${UPLOAD_NOTIFY_PENDING_WORK_PREFIX}${item.workId}`;
  await env.STAR_KV.put(key, JSON.stringify(item));
  await writeUploadNotificationWorkStatus(env, item.workId, {
    notificationState: "queued",
    reason: "queued",
    queuedAt: item.queuedAt,
    lastAttemptAt: "",
    lastSentAt: "",
    targetRecipients: 0,
    sentRecipients: 0,
    failedRecipients: 0,
  });
  return { queued: true, reason: "", key };
}

async function listKvKeysByPrefix(kv, prefix) {
  const names = [];
  let cursor = undefined;
  while (true) {
    const response = await kv.list({ prefix, cursor, limit: 1000 });
    const keys = Array.isArray(response?.keys) ? response.keys : [];
    names.push(...keys.map((entry) => asString(entry?.name)).filter(Boolean));
    if (response?.list_complete) break;
    const nextCursor = asString(response?.cursor);
    if (!nextCursor) break;
    cursor = nextCursor;
  }
  return names;
}

async function loadPendingWorkNotificationBatch(env) {
  if (!env.STAR_KV) {
    return { ok: false, reason: "kv_not_configured", items: [], validKeys: [], invalidKeys: [] };
  }

  const keys = await listKvKeysByPrefix(env.STAR_KV, UPLOAD_NOTIFY_PENDING_WORK_PREFIX);
  if (keys.length === 0) {
    return { ok: true, reason: "no_items", items: [], validKeys: [], invalidKeys: [] };
  }

  const validKeys = [];
  const invalidKeys = [];
  const items = [];

  const readBatchSize = 50;
  for (let offset = 0; offset < keys.length; offset += readBatchSize) {
    const batchKeys = keys.slice(offset, offset + readBatchSize);
    const rawValues = await Promise.all(batchKeys.map((key) => env.STAR_KV.get(key)));

    for (let i = 0; i < batchKeys.length; i += 1) {
      const key = batchKeys[i];
      const raw = rawValues[i];
      if (!raw) {
        invalidKeys.push(key);
        continue;
      }

      let parsed = null;
      try {
        parsed = JSON.parse(raw);
      } catch {
        invalidKeys.push(key);
        continue;
      }

      const workId = asString(parsed?.workId).trim();
      if (!workId) {
        invalidKeys.push(key);
        continue;
      }
      const authorIds = uniqueIds(Array.isArray(parsed?.authorIds) ? parsed.authorIds : []);
      const hasPendingAuthorIdsField = Array.isArray(parsed?.pendingAuthorIds);
      const pendingAuthorIdsRaw = uniqueIds(hasPendingAuthorIdsField ? parsed.pendingAuthorIds : authorIds);
      const mergedAuthorIds = uniqueIds([...authorIds, ...pendingAuthorIdsRaw]);
      const pendingAuthorIds = pendingAuthorIdsRaw.length > 0 ? [...pendingAuthorIdsRaw] : [];
      if (mergedAuthorIds.length === 0 || pendingAuthorIds.length === 0) {
        invalidKeys.push(key);
        continue;
      }
      const pendingAuthorIdsDerived = !hasPendingAuthorIdsField || isSameIdSet(pendingAuthorIds, mergedAuthorIds);

      validKeys.push(key);
      items.push({
        key,
        title: asString(parsed?.title).trim(),
        completedDate: normalizeYmd(parsed?.completedDate) || asString(parsed?.completedDate).trim(),
        classroom: asString(parsed?.classroom).trim(),
        queuedAt: asString(parsed?.queuedAt).trim(),
        imageCount: Math.max(0, Number.isFinite(Number(parsed?.imageCount)) ? Math.floor(Number(parsed?.imageCount)) : 0),
        authorIds: mergedAuthorIds,
        pendingAuthorIds,
        pendingAuthorIdsDerived,
        workId,
      });
    }
  }

  return { ok: true, reason: "", items, validKeys, invalidKeys };
}

async function deleteKvKeys(kv, keys) {
  if (!kv || !Array.isArray(keys) || keys.length === 0) return;
  await Promise.all(keys.map((key) => kv.delete(key)));
}

function uploadNotifyStatusKey(workId) {
  return `${UPLOAD_NOTIFY_STATUS_WORK_PREFIX}${asString(workId).trim()}`;
}

function uploadNotifyDisabledKey(workId) {
  return `${UPLOAD_NOTIFY_DISABLED_WORK_PREFIX}${asString(workId).trim()}`;
}

function isUploadNotificationDisabledStoredValue(value) {
  const raw = asString(value).trim();
  if (!raw) return false;
  if (isFalsyString(raw)) return false;
  if (isTruthyString(raw)) return true;
  return raw === "1";
}

async function setUploadNotificationDisabledByWorkId(env, workId, disabled) {
  if (!env.STAR_KV) return { ok: false, reason: "kv_not_configured" };
  const id = asString(workId).trim();
  if (!id) return { ok: false, reason: "missing_work_id" };

  try {
    const key = uploadNotifyDisabledKey(id);
    if (disabled) {
      await env.STAR_KV.put(key, "1");
      await env.STAR_KV.delete(`${UPLOAD_NOTIFY_PENDING_WORK_PREFIX}${id}`);
      await writeUploadNotificationWorkStatus(env, id, {
        notificationState: "disabled",
        reason: "work_notify_disabled",
        queuedAt: "",
        lastAttemptAt: new Date().toISOString(),
        lastSentAt: "",
        targetRecipients: 0,
        sentRecipients: 0,
        failedRecipients: 0,
      });
      return { ok: true, reason: "", disabled: true, workId: id };
    }

    await env.STAR_KV.delete(key);
    return { ok: true, reason: "", disabled: false, workId: id };
  } catch (error) {
    console.error("failed to update work notification disable flag", {
      workId: id,
      disabled: Boolean(disabled),
      message: asString(error?.message),
    });
    return { ok: false, reason: "kv_write_failed" };
  }
}

async function loadUploadNotificationDisabledByWorkIds(env, workIdsRaw) {
  const workIds = uniqueIds(Array.isArray(workIdsRaw) ? workIdsRaw : []);
  if (workIds.length === 0) {
    return {
      ok: true,
      reason: "",
      disabledWorkIdSet: new Set(),
    };
  }
  if (!env.STAR_KV) {
    return {
      ok: false,
      reason: "kv_not_configured",
      disabledWorkIdSet: new Set(),
    };
  }

  const disabledWorkIdSet = new Set();
  const batchSize = 50;
  for (let offset = 0; offset < workIds.length; offset += batchSize) {
    const batch = workIds.slice(offset, offset + batchSize);
    const rawValues = await Promise.all(batch.map((workId) => env.STAR_KV.get(uploadNotifyDisabledKey(workId))));
    for (let i = 0; i < batch.length; i += 1) {
      const workId = batch[i];
      const raw = rawValues[i];
      if (!isUploadNotificationDisabledStoredValue(raw)) continue;
      disabledWorkIdSet.add(workId);
    }
  }

  return {
    ok: true,
    reason: "",
    disabledWorkIdSet,
  };
}

async function clearUploadNotificationTrackingForWork(env, workId) {
  const id = asString(workId).trim();
  if (!id) return { ok: false, reason: "missing_work_id" };
  if (!env.STAR_KV) return { ok: false, reason: "kv_not_configured" };

  try {
    await deleteKvKeys(env.STAR_KV, [
      `${UPLOAD_NOTIFY_PENDING_WORK_PREFIX}${id}`,
      uploadNotifyStatusKey(id),
      uploadNotifyDisabledKey(id),
    ]);
    return { ok: true, reason: "", workId: id };
  } catch (error) {
    console.error("failed to clear work notification tracking", {
      workId: id,
      message: asString(error?.message),
    });
    return { ok: false, reason: "kv_delete_failed", workId: id };
  }
}

async function writeUploadNotificationWorkStatus(env, workId, patch) {
  if (!env.STAR_KV) return false;
  const id = asString(workId).trim();
  if (!id) return false;
  const payload = {
    workId: id,
    ...patch,
    updatedAt: new Date().toISOString(),
  };
  try {
    await env.STAR_KV.put(uploadNotifyStatusKey(id), JSON.stringify(payload));
    return true;
  } catch (error) {
    console.error("failed to write upload notification work status", {
      workId: id,
      message: asString(error?.message),
    });
    return false;
  }
}

async function writeUploadNotificationWorkStatuses(env, updates) {
  if (!env.STAR_KV || !Array.isArray(updates) || updates.length === 0) return;
  await Promise.all(
    updates.map(async (entry) => {
      const workId = asString(entry?.workId).trim();
      if (!workId) return;
      await writeUploadNotificationWorkStatus(env, workId, entry.patch || {});
    }),
  );
}

function deriveUploadNotificationStateFromDelivery(stats) {
  const targetRecipients = Number(stats?.targetRecipients) || 0;
  const sentRecipients = Number(stats?.sentRecipients) || 0;
  const failedRecipients = Number(stats?.failedRecipients) || 0;
  if (sentRecipients > 0 && failedRecipients > 0) return "partial";
  if (sentRecipients > 0) return "sent";
  if (failedRecipients > 0) return "failed";
  if (targetRecipients === 0) return "no_recipients";
  return "queued";
}

async function notifyStudentsOnUploadBatch(env, itemsRaw) {
  const normalizedWorks = normalizeUploadBatchNotificationItems(itemsRaw);
  if (normalizedWorks.length === 0) {
    return {
      enabled: true,
      attempted: false,
      reason: "no_items",
      works: 0,
      recipients: 0,
      sent: 0,
      failed: 0,
      skippedNoEmail: 0,
      skippedOptOut: 0,
      skippedNotFound: 0,
      workPendingAuthorIds: [],
    };
  }

  const works = await enrichUploadBatchWorksWithNotionAuthors(env, normalizedWorks);
  const workIds = uniqueIds(works.map((work) => asString(work?.workId).trim()));
  const disabledSnapshot = await loadUploadNotificationDisabledByWorkIds(env, workIds);
  const disabledWorkIdSet = disabledSnapshot.disabledWorkIdSet;
  const disabledWorks = works.filter((work) => disabledWorkIdSet.has(asString(work?.workId).trim()));
  const activeWorks = works.filter((work) => !disabledWorkIdSet.has(asString(work?.workId).trim()));

  if (disabledWorks.length > 0) {
    await writeUploadNotificationWorkStatuses(
      env,
      disabledWorks
        .map((work) => ({
          workId: asString(work?.workId).trim(),
          patch: {
            notificationState: "disabled",
            reason: "work_notify_disabled",
            queuedAt: asString(work?.queuedAt).trim(),
            lastAttemptAt: new Date().toISOString(),
            lastSentAt: "",
            targetRecipients: 0,
            sentRecipients: 0,
            failedRecipients: 0,
          },
        }))
        .filter((entry) => entry.workId),
    );
  }

  if (activeWorks.length === 0) {
    return {
      enabled: true,
      attempted: true,
      reason: "work_notify_disabled",
      works: works.length,
      recipients: 0,
      sent: 0,
      failed: 0,
      skippedNoEmail: 0,
      skippedOptOut: 0,
      skippedNotFound: 0,
      workPendingAuthorIds: [],
    };
  }

  const pendingAuthorIdsByWorkId = new Map(
    activeWorks
      .map((work) => {
        const workId = asString(work?.workId).trim();
        if (!workId) return null;
        const pendingAuthorIds = uniqueIds(Array.isArray(work?.pendingAuthorIds) ? work.pendingAuthorIds : work.authorIds);
        if (pendingAuthorIds.length === 0) return null;
        return [workId, new Set(pendingAuthorIds)];
      })
      .filter(Boolean),
  );
  const serializeWorkPendingAuthorIds = () =>
    Array.from(pendingAuthorIdsByWorkId.entries())
      .map(([workId, pendingAuthorIdSet]) => ({
        workId,
        pendingAuthorIds: Array.from(pendingAuthorIdSet.values()),
      }))
      .filter((entry) => entry.workId);

  const config = getUploadNotificationConfig(env);
  if (!config.enabled) {
    await writeUploadNotificationWorkStatuses(
      env,
      activeWorks
        .map((work) => ({
          workId: work.workId,
          patch: {
            notificationState: "queued",
            reason: config.reason,
            queuedAt: asString(work.queuedAt).trim(),
            lastAttemptAt: "",
            lastSentAt: "",
            targetRecipients: 0,
            sentRecipients: 0,
            failedRecipients: 0,
          },
        }))
        .filter((entry) => entry.workId),
    );
    return {
      enabled: false,
      attempted: false,
      reason: config.reason,
      works: works.length,
      recipients: 0,
      sent: 0,
      failed: 0,
      skippedNoEmail: 0,
      skippedOptOut: 0,
      skippedNotFound: 0,
      workPendingAuthorIds: serializeWorkPendingAuthorIds(),
    };
  }

  const deliveryStatsByWorkId = new Map(
    activeWorks
      .map((work) => {
        const workId = asString(work?.workId).trim();
        if (!workId) return null;
        return [
          workId,
          {
            workId,
            queuedAt: asString(work?.queuedAt).trim(),
            targetRecipients: 0,
            sentRecipients: 0,
            failedRecipients: 0,
          },
        ];
      })
      .filter(Boolean),
  );

  const authorIds = uniqueIds(Array.from(pendingAuthorIdsByWorkId.values()).flatMap((set) => Array.from(set.values())));
  if (authorIds.length === 0) {
    await writeUploadNotificationWorkStatuses(
      env,
      Array.from(deliveryStatsByWorkId.values()).map((stats) => ({
        workId: stats.workId,
        patch: {
          notificationState: "no_authors",
          reason: "no_authors",
          queuedAt: stats.queuedAt,
          lastAttemptAt: "",
          lastSentAt: "",
          targetRecipients: 0,
          sentRecipients: 0,
          failedRecipients: 0,
        },
      })),
    );
    return {
      enabled: true,
      attempted: false,
      reason: "no_authors",
      works: works.length,
      recipients: 0,
      sent: 0,
      failed: 0,
      skippedNoEmail: 0,
      skippedOptOut: 0,
      skippedNotFound: 0,
      workPendingAuthorIds: serializeWorkPendingAuthorIds(),
    };
  }

  const recipientsResult = await collectStudentNotificationRecipients(env, authorIds);
  if (!recipientsResult.ok) {
    await writeUploadNotificationWorkStatuses(
      env,
      Array.from(deliveryStatsByWorkId.values()).map((stats) => ({
        workId: stats.workId,
        patch: {
          notificationState: "queued",
          reason: recipientsResult.reason || "recipients_resolve_failed",
          queuedAt: stats.queuedAt,
          lastAttemptAt: "",
          lastSentAt: "",
          targetRecipients: 0,
          sentRecipients: 0,
          failedRecipients: 0,
        },
      })),
    );
    return {
      enabled: true,
      attempted: false,
      reason: recipientsResult.reason || "recipients_resolve_failed",
      works: works.length,
      recipients: 0,
      sent: 0,
      failed: 0,
      skippedNoEmail: recipientsResult.skippedNoEmail ?? 0,
      skippedOptOut: recipientsResult.skippedOptOut ?? 0,
      skippedNotFound: recipientsResult.skippedNotFound ?? authorIds.length,
      workPendingAuthorIds: serializeWorkPendingAuthorIds(),
    };
  }

  const terminalSkippedAuthorIds = uniqueIds(
    Array.isArray(recipientsResult?.terminalSkippedAuthorIds) ? recipientsResult.terminalSkippedAuthorIds : [],
  );
  if (terminalSkippedAuthorIds.length > 0) {
    for (const pendingAuthorIdSet of pendingAuthorIdsByWorkId.values()) {
      terminalSkippedAuthorIds.forEach((authorId) => pendingAuthorIdSet.delete(authorId));
    }
  }

  const worksByAuthorId = new Map();
  for (const work of activeWorks) {
    const workId = asString(work?.workId).trim();
    const pendingAuthorIds = workId
      ? uniqueIds(Array.from(pendingAuthorIdsByWorkId.get(workId)?.values() || []))
      : uniqueIds(Array.isArray(work?.pendingAuthorIds) ? work.pendingAuthorIds : []);
    for (const authorId of pendingAuthorIds) {
      if (!worksByAuthorId.has(authorId)) worksByAuthorId.set(authorId, []);
      worksByAuthorId.get(authorId).push(work);
    }
  }

  const recipients = (recipientsResult.recipients || []).filter((recipient) =>
    (Array.isArray(recipient.authorIds) ? recipient.authorIds : []).some((authorId) => worksByAuthorId.has(authorId)),
  );
  if (recipients.length === 0) {
    await writeUploadNotificationWorkStatuses(
      env,
      Array.from(deliveryStatsByWorkId.values()).map((stats) => ({
        workId: stats.workId,
        patch: {
          notificationState: "no_recipients",
          reason: "no_recipients",
          queuedAt: stats.queuedAt,
          lastAttemptAt: new Date().toISOString(),
          lastSentAt: "",
          targetRecipients: 0,
          sentRecipients: 0,
          failedRecipients: 0,
        },
      })),
    );
    return {
      enabled: true,
      attempted: true,
      reason: "no_recipients",
      works: works.length,
      recipients: 0,
      sent: 0,
      failed: 0,
      skippedNoEmail: recipientsResult.skippedNoEmail,
      skippedOptOut: recipientsResult.skippedOptOut,
      skippedNotFound: recipientsResult.skippedNotFound,
      workPendingAuthorIds: serializeWorkPendingAuthorIds(),
    };
  }

  let sent = 0;
  let failed = 0;
  const minIntervalMs = Number.isFinite(Number(config?.minIntervalMs))
    ? Math.max(0, Math.floor(Number(config.minIntervalMs)))
    : 600;
  let nextSendAt = 0;
  const attemptStartedAt = new Date().toISOString();
  for (const recipient of recipients) {
    const authorIdsForRecipient = uniqueIds(Array.isArray(recipient.authorIds) ? recipient.authorIds : []);
    const workIdSetForRecipient = new Set();
    const worksForRecipient = [];
    for (const authorId of authorIdsForRecipient) {
      const worksForAuthor = worksByAuthorId.get(authorId) || [];
      for (const work of worksForAuthor) {
        const workId = asString(work?.workId).trim();
        if (!workId || workIdSetForRecipient.has(workId)) continue;
        workIdSetForRecipient.add(workId);
        worksForRecipient.push(work);
      }
    }
    if (worksForRecipient.length === 0) continue;
    const content = buildUploadBatchNotificationContent(env, recipient, worksForRecipient);
    const workIdsForRecipient = Array.from(workIdSetForRecipient.values());
    workIdsForRecipient.forEach((workId) => {
      const stats = deliveryStatsByWorkId.get(workId);
      if (!stats) return;
      stats.targetRecipients += 1;
    });

    const waitMs = nextSendAt - Date.now();
    if (waitMs > 0) {
      await sleep(waitMs);
    }
    if (minIntervalMs > 0) {
      nextSendAt = Date.now() + minIntervalMs;
    }

    try {
      await sendUploadNotificationWithResend(config, recipient.email, content);
      sent += 1;
      workIdsForRecipient.forEach((workId) => {
        const stats = deliveryStatsByWorkId.get(workId);
        if (!stats) return;
        stats.sentRecipients += 1;
        const pendingAuthorIdSet = pendingAuthorIdsByWorkId.get(workId);
        if (!pendingAuthorIdSet) return;
        authorIdsForRecipient.forEach((authorId) => pendingAuthorIdSet.delete(authorId));
      });
    } catch (error) {
      failed += 1;
      workIdsForRecipient.forEach((workId) => {
        const stats = deliveryStatsByWorkId.get(workId);
        if (!stats) return;
        stats.failedRecipients += 1;
      });
      console.error("student upload batch notification failed", {
        authorIds: authorIdsForRecipient,
        works: worksForRecipient.length,
        message: asString(error?.message),
      });
    }
  }

  const updates = Array.from(deliveryStatsByWorkId.values()).map((stats) => {
    const notificationState = deriveUploadNotificationStateFromDelivery(stats);
    return {
      workId: stats.workId,
      patch: {
        notificationState,
        reason: notificationState,
        queuedAt: stats.queuedAt,
        lastAttemptAt: attemptStartedAt,
        lastSentAt: notificationState === "sent" || notificationState === "partial" ? new Date().toISOString() : "",
        targetRecipients: stats.targetRecipients,
        sentRecipients: stats.sentRecipients,
        failedRecipients: stats.failedRecipients,
      },
    };
  });
  await writeUploadNotificationWorkStatuses(env, updates);

  return {
    enabled: true,
    attempted: true,
    reason: "",
    works: works.length,
    recipients: recipients.length,
    sent,
    failed,
    skippedNoEmail: recipientsResult.skippedNoEmail,
    skippedOptOut: recipientsResult.skippedOptOut,
    skippedNotFound: recipientsResult.skippedNotFound,
    workPendingAuthorIds: serializeWorkPendingAuthorIds(),
  };
}

async function handleNotifyStudentsAfterGalleryUpdate(env) {
  if (!env.STAR_KV) return serverError("KV binding not configured (STAR_KV)");

  const loaded = await loadPendingWorkNotificationBatch(env);
  if (!loaded.ok) {
    return serverError(`failed to load pending notifications: ${loaded.reason}`);
  }

  if (loaded.invalidKeys.length > 0) {
    await deleteKvKeys(env.STAR_KV, loaded.invalidKeys);
  }

  if (loaded.items.length === 0) {
    return okResponse({
      notification: {
        enabled: true,
        attempted: false,
        reason: "no_items",
        works: 0,
        recipients: 0,
        sent: 0,
        failed: 0,
        skippedNoEmail: 0,
        skippedOptOut: 0,
        skippedNotFound: 0,
      },
      pendingWorks: 0,
      cleanedInvalid: loaded.invalidKeys.length,
    });
  }

  let notification;
  try {
    notification = await notifyStudentsOnUploadBatch(env, loaded.items);
  } catch (error) {
    console.error("student upload post-gallery notification unexpected error", {
      message: asString(error?.message),
    });
    return jsonResponse(
      {
        ok: false,
        error: "failed to send notifications after gallery update",
        detail: asString(error?.message),
        pendingWorks: loaded.validKeys.length,
      },
      500,
    );
  }

  const reason = asString(notification?.reason).trim();
  const keepPendingForConfigIssues = new Set(["disabled", "not_configured", "invalid_from_email"]).has(reason);
  const notAttempted = notification?.attempted === false;
  const clearAllForTerminalReason = new Set(["no_items", "no_authors", "no_recipients"]).has(reason);
  const keepPendingForRecoverableNotAttempted = notAttempted && !clearAllForTerminalReason;

  if (clearAllForTerminalReason) {
    await deleteKvKeys(env.STAR_KV, loaded.validKeys);
    return okResponse({
      notification,
      pendingWorks: 0,
      processedWorks: loaded.validKeys.length,
      cleanedInvalid: loaded.invalidKeys.length,
      queueCleared: true,
    });
  }

  if (keepPendingForConfigIssues || keepPendingForRecoverableNotAttempted) {
    return okResponse({
      notification,
      pendingWorks: loaded.validKeys.length,
      processedWorks: loaded.validKeys.length,
      cleanedInvalid: loaded.invalidKeys.length,
      queueCleared: false,
    });
  }

  const remainingPendingByWorkId = new Map(
    (Array.isArray(notification?.workPendingAuthorIds) ? notification.workPendingAuthorIds : [])
      .map((entry) => {
        const workId = asString(entry?.workId).trim();
        if (!workId) return null;
        return [workId, uniqueIds(Array.isArray(entry?.pendingAuthorIds) ? entry.pendingAuthorIds : [])];
      })
      .filter(Boolean),
  );

  const keysToDelete = [];
  const itemsToUpsert = [];
  for (const item of loaded.items) {
    const workId = asString(item?.workId).trim();
    const key = asString(item?.key).trim() || `${UPLOAD_NOTIFY_PENDING_WORK_PREFIX}${workId}`;
    if (!workId || !key) continue;

    const pendingAuthorIds = remainingPendingByWorkId.get(workId) || [];
    const nextItem = buildPendingWorkNotificationItemFromSnapshot(item, pendingAuthorIds);
    if (!nextItem) {
      keysToDelete.push(key);
      continue;
    }
    itemsToUpsert.push({ key, value: JSON.stringify(nextItem) });
  }

  if (keysToDelete.length > 0) {
    await deleteKvKeys(env.STAR_KV, keysToDelete);
  }
  if (itemsToUpsert.length > 0) {
    await Promise.all(itemsToUpsert.map((entry) => env.STAR_KV.put(entry.key, entry.value)));
  }

  const pendingWorks = itemsToUpsert.length;
  return okResponse({
    notification,
    pendingWorks,
    processedWorks: loaded.validKeys.length,
    cleanedInvalid: loaded.invalidKeys.length,
    queueCleared: pendingWorks === 0,
  });
}

function parsePendingNotificationWorkIdFromKey(key) {
  const name = asString(key);
  if (!name.startsWith(UPLOAD_NOTIFY_PENDING_WORK_PREFIX)) return "";
  return asString(name.slice(UPLOAD_NOTIFY_PENDING_WORK_PREFIX.length)).trim();
}

async function loadUploadNotificationStatusByWorkIds(env, workIdsRaw) {
  const workIds = uniqueIds(Array.isArray(workIdsRaw) ? workIdsRaw : []);
  if (workIds.length === 0) {
    return {
      ok: true,
      reason: "",
      pendingWorkIdSet: new Set(),
      statusByWorkId: new Map(),
    };
  }
  if (!env.STAR_KV) {
    return {
      ok: false,
      reason: "kv_not_configured",
      pendingWorkIdSet: new Set(),
      statusByWorkId: new Map(),
    };
  }

  const pendingKeys = await listKvKeysByPrefix(env.STAR_KV, UPLOAD_NOTIFY_PENDING_WORK_PREFIX);
  const pendingWorkIdSet = new Set(pendingKeys.map(parsePendingNotificationWorkIdFromKey).filter(Boolean));

  const statusByWorkId = new Map();
  const batchSize = 50;
  for (let offset = 0; offset < workIds.length; offset += batchSize) {
    const batch = workIds.slice(offset, offset + batchSize);
    const rawValues = await Promise.all(batch.map((workId) => env.STAR_KV.get(uploadNotifyStatusKey(workId))));
    for (let i = 0; i < batch.length; i += 1) {
      const workId = batch[i];
      const raw = rawValues[i];
      if (!raw) continue;
      try {
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object") continue;
        statusByWorkId.set(workId, parsed);
      } catch {
        // ignore malformed records
      }
    }
  }

  return {
    ok: true,
    reason: "",
    pendingWorkIdSet,
    statusByWorkId,
  };
}

async function loadGalleryWorkIdSetForAdmin(env) {
  const result = {
    ok: false,
    reason: "gallery_not_found",
    workIdSet: new Set(),
  };

  let galleryPayload = null;

  const galleryUrl = getEnvString(env, "GALLERY_JSON_URL");
  if (galleryUrl) {
    try {
      const res = await fetch(galleryUrl, { method: "GET" });
      if (res.ok) {
        const parsed = await res.json().catch(() => null);
        if (parsed) {
          galleryPayload = parsed;
          result.ok = true;
          result.reason = "";
        }
      }
    } catch {
      // try R2 fallback
    }
  }

  if (!galleryPayload && env.GALLERY_R2) {
    const key = getEnvString(env, "GALLERY_JSON_KEY", "gallery.json");
    try {
      const obj = await env.GALLERY_R2.get(key);
      if (obj) {
        const text = await obj.text();
        const parsed = JSON.parse(text);
        if (parsed) {
          galleryPayload = parsed;
          result.ok = true;
          result.reason = "";
        }
      }
    } catch {
      result.reason = "gallery_parse_failed";
    }
  }

  const worksArray = Array.isArray(galleryPayload?.works)
    ? galleryPayload.works
    : Array.isArray(galleryPayload)
      ? galleryPayload
      : [];
  for (const work of worksArray) {
    const workId = asString(work?.id).trim();
    if (!workId) continue;
    result.workIdSet.add(workId);
  }
  return result;
}

function deriveUiNotificationState(rawState, pending) {
  const base = asString(rawState).trim();
  if (pending) {
    if (base === "failed" || base === "partial") return "retry_pending";
    return "queued";
  }
  return base || "unknown";
}

async function handleAdminCurationWorkSyncStatus(request, env) {
  const payload = await readJson(request);
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return badRequest("invalid json");

  const workIds = uniqueIds(Array.isArray(payload.workIds) ? payload.workIds : []);
  if (workIds.length === 0) {
    return okResponse({
      statuses: [],
      pendingCount: 0,
      galleryLoaded: false,
      notificationStatusLoaded: true,
      snapshotAt: new Date().toISOString(),
    });
  }

  const [notificationSnapshot, gallerySnapshot, disabledSnapshot] = await Promise.all([
    loadUploadNotificationStatusByWorkIds(env, workIds),
    loadGalleryWorkIdSetForAdmin(env),
    loadUploadNotificationDisabledByWorkIds(env, workIds),
  ]);

  const statuses = workIds.map((workId) => {
    const pending = notificationSnapshot.pendingWorkIdSet.has(workId);
    const rawStatus = notificationSnapshot.statusByWorkId.get(workId);
    const rawState = asString(rawStatus?.notificationState).trim();
    const notificationDisabled = disabledSnapshot.disabledWorkIdSet.has(workId);
    return {
      workId,
      pending,
      galleryReflected: gallerySnapshot.ok ? gallerySnapshot.workIdSet.has(workId) : null,
      notification: {
        notificationDisabled,
        notificationState: deriveUiNotificationState(rawState, pending),
        rawState,
        reason: asString(rawStatus?.reason).trim(),
        queuedAt: asString(rawStatus?.queuedAt).trim(),
        lastAttemptAt: asString(rawStatus?.lastAttemptAt).trim(),
        lastSentAt: asString(rawStatus?.lastSentAt).trim(),
        targetRecipients: Number(rawStatus?.targetRecipients) || 0,
        sentRecipients: Number(rawStatus?.sentRecipients) || 0,
        failedRecipients: Number(rawStatus?.failedRecipients) || 0,
        updatedAt: asString(rawStatus?.updatedAt).trim(),
      },
    };
  });

  return okResponse({
    statuses,
    pendingCount: statuses.filter((row) => row.pending).length,
    galleryLoaded: gallerySnapshot.ok,
    notificationStatusLoaded: Boolean(notificationSnapshot.ok && disabledSnapshot.ok),
    notificationStatusReason: notificationSnapshot.reason || disabledSnapshot.reason || "",
    snapshotAt: new Date().toISOString(),
  });
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
  const workId = asString(res.data?.id);
  const notificationDisabled = Boolean(payload.notificationDisabled);
  let notificationPreferenceReason = "";
  if (notificationDisabled) {
    const updated = await setUploadNotificationDisabledByWorkId(env, workId, true);
    if (!updated.ok) {
      notificationPreferenceReason = updated.reason || "notification_pref_not_saved";
    }
  }
  const notificationMode = asString(payload.notificationMode).trim().toLowerCase();
  const shouldQueueNotification =
    !notificationDisabled && !["skip", "off", "none", "disabled", "false", "0"].includes(notificationMode);

  let notification = {
    queued: 0,
    attempted: false,
    reason: shouldQueueNotification
      ? "not_queued"
      : notificationDisabled
        ? notificationPreferenceReason || "work_notify_disabled"
        : "skipped_by_request",
  };
  if (shouldQueueNotification) {
    const queued = await queuePendingWorkNotification(env, workId, payload);
    notification = {
      queued: queued.queued ? 1 : 0,
      attempted: false,
      reason: queued.reason || "",
    };
  }

  return okResponse({ id: workId, notification, notificationDisabled }, 201);
}

async function handleNotionUpdateWork(request, env) {
  const payload = await readJson(request);
  if (!payload || typeof payload !== "object") return badRequest("invalid json");
  const id = asString(payload.id).trim();
  if (!id) return badRequest("missing id");
  const hasNotificationDisabled = Object.prototype.hasOwnProperty.call(payload, "notificationDisabled");
  const notificationDisabled = Boolean(payload.notificationDisabled);

  const props = pickWorkProperties(env, payload);
  const body = {};
  if (Object.keys(props).length > 0) body.properties = props;

  if ("archived" in payload) body.archived = Boolean(payload.archived);

  if (Object.keys(body).length === 0 && !hasNotificationDisabled) return badRequest("no updates");

  let notionUpdated = false;
  if (Object.keys(body).length > 0) {
    const res = await notionFetch(env, `/pages/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      return jsonResponse({ ok: false, error: "failed to update notion page", detail: res.data }, 500);
    }
    notionUpdated = true;
  }

  if (hasNotificationDisabled) {
    const updated = await setUploadNotificationDisabledByWorkId(env, id, notificationDisabled);
    if (!updated.ok) {
      return jsonResponse(
        {
          ok: false,
          error: "failed to update work notification preference",
          reason: updated.reason || "",
          notionUpdated,
        },
        500,
      );
    }
  }

  if (payload.archived === true) {
    await clearUploadNotificationTrackingForWork(env, id);
  }

  const response = { id };
  if (hasNotificationDisabled) response.notificationDisabled = notificationDisabled;
  return okResponse(response);
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
  const aliasesRaw = normalizeTagAliasValues(payload.aliases);
  const aliases = aliasesRaw.filter((alias) => normalizeTagNameKey(alias) !== normalizeTagNameKey(name));

  const tagsDbRes = await notionFetch(env, `/databases/${tagsDbId}`, { method: "GET" });
  if (!tagsDbRes.ok) {
    return jsonResponse({ ok: false, error: "failed to fetch tags database", detail: tagsDbRes.data }, 500);
  }
  const tagsDb = tagsDbRes.data;
  const tagsProps = getTagsProps(env);
  const titleProp = pickPropertyName(tagsDb, [tagsProps.title, "タグ"], "title");
  const statusProp = pickPropertyName(tagsDb, [tagsProps.status, "状態"], "");
  const aliasesProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_ALIASES_PROP", "別名"), "別名"], "");
  const parentsProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_PARENTS_PROP", "親タグ"), "親タグ"], "");
  const childrenProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_CHILDREN_PROP", "子タグ"), "子タグ"], "");
  if (parentIds.length > 0 && !parentsProp) return badRequest("親タグプロパティが見つかりません");
  if (childIds.length > 0 && !childrenProp) return badRequest("子タグプロパティが見つかりません");
  if (aliases.length > 0 && !aliasesProp) return badRequest("別名プロパティが見つかりません");

  const tagsQueryRes = await queryAllDatabasePages(env, tagsDbId);
  if (!tagsQueryRes.ok) {
    return jsonResponse({ ok: false, error: "failed to query tags database", detail: tagsQueryRes.data }, 500);
  }
  const tagsIndexSnapshot = buildTagsIndexFromNotion(env, tagsDbId, tagsDb, tagsQueryRes.pages);
  const duplicateTag = findExistingTagByNameOrAlias(tagsIndexSnapshot.tags, [name, ...aliases]);
  if (duplicateTag) {
    return jsonResponse(
      {
        ok: false,
        error: "同名または別名のタグが既に存在します",
        existing_id: duplicateTag.id,
        existing_tag: duplicateTag,
      },
      409,
    );
  }

  const properties = {};
  properties[titleProp || tagsProps.title || "タグ"] = notionTitle(name);
  if (parentsProp && parentIds.length > 0) properties[parentsProp] = notionRelation(parentIds);
  if (childrenProp && childIds.length > 0) properties[childrenProp] = notionRelation(childIds);
  if (aliasesProp && aliases.length > 0) {
    const aliasesPropSchema = tagsDb?.properties?.[aliasesProp] || null;
    if (aliasesPropSchema?.type === "multi_select") {
      properties[aliasesProp] = notionMultiSelect(aliases);
    } else {
      properties[aliasesProp] = notionRichText(aliases.join(", "));
    }
  }

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

  const tagsIndex = await refreshTagsIndexAfterTagMutation(env);
  return okResponse(
    {
      id: asString(res.data?.id),
      name,
      status: statusName || "active",
      parents: parentIds,
      children: childIds,
      aliases,
      merge_to: "",
      usage_count: 0,
      tags_index: tagsIndex,
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
  const statusProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_STATUS_PROP", "状態"), "状態"], "");
  const aliasesProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_ALIASES_PROP", "別名"), "別名"], "");
  const mergeToProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_MERGE_TO_PROP", "統合先"), "統合先"], "");
  const parentsProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_PARENTS_PROP", "親タグ"), "親タグ"], "");
  const childrenProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_CHILDREN_PROP", "子タグ"), "子タグ"], "");
  const usageCountProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_USAGE_COUNT_PROP", "作品数"), "作品数"], "");
  const worksRelProp = pickPropertyName(tagsDb, [getEnvString(env, "NOTION_TAGS_WORKS_REL_PROP", "作品"), "作品"], "");
  const withTagsIndex = async (body) => {
    const tagsIndex = await refreshTagsIndexAfterTagMutation(env);
    return { ...body, tags_index: tagsIndex };
  };

  const loadTagPage = async (id) => {
    const res = await notionFetch(env, `/pages/${id}`, { method: "GET" });
    if (!res.ok) {
      return { ok: false, detail: res.data };
    }
    return { ok: true, page: res.data };
  };

  const buildTagResponseFromPage = (page) => {
    const id = asString(page?.id).trim();
    const name = extractPropertyText(getPageProperty(page, titleProp)).trim();
    const status = normalizeTagStatus(extractPropertyText(getPageProperty(page, statusProp)));
    const aliases = extractAliases(getPageProperty(page, aliasesProp)).filter(
      (alias) => normalizeTagNameKey(alias) !== normalizeTagNameKey(name),
    );
    const mergeTo = extractRelationIds(getPageProperty(page, mergeToProp))[0] || "";
    const parents = parentsProp ? extractRelationIds(getPageProperty(page, parentsProp)) : [];
    const children = childrenProp ? extractRelationIds(getPageProperty(page, childrenProp)) : [];
    let usageCount = Math.max(0, Math.floor(extractPropertyNumber(getPageProperty(page, usageCountProp))));
    if (!usageCount && worksRelProp) {
      usageCount = Math.max(0, extractRelationIds(getPageProperty(page, worksRelProp)).length);
    }
    return {
      id,
      name,
      status,
      aliases,
      merge_to: mergeTo,
      parents,
      children,
      usage_count: usageCount,
    };
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
        tag: buildTagResponseFromPage(page),
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

    const nextPage = patchRes.data && typeof patchRes.data === "object" ? patchRes.data : page;
    return {
      ok: true,
      tag: buildTagResponseFromPage(nextPage),
    };
  };

  const patchTagAliases = async ({ id, aliases }) => {
    const tagId = asString(id).trim();
    if (!tagId) return { ok: false, error: "missing tag id" };
    if (!aliasesProp) return { ok: false, error: "aliases property not found" };

    const loaded = await loadTagPage(tagId);
    if (!loaded.ok) {
      return { ok: false, error: "failed to fetch tag page", detail: loaded.detail };
    }
    const page = loaded.page;
    const currentTag = buildTagResponseFromPage(page);
    const nextAliases = normalizeTagAliasValues(aliases).filter(
      (alias) => normalizeTagNameKey(alias) !== normalizeTagNameKey(currentTag.name),
    );
    const currentAliasKeys = new Set(
      (Array.isArray(currentTag.aliases) ? currentTag.aliases : []).map((value) => normalizeTagNameKey(value)).filter(Boolean),
    );
    const nextAliasKeys = new Set(nextAliases.map((value) => normalizeTagNameKey(value)).filter(Boolean));
    const aliasesChanged =
      currentAliasKeys.size !== nextAliasKeys.size || [...currentAliasKeys].some((key) => !nextAliasKeys.has(key));

    if (!aliasesChanged) {
      return {
        ok: true,
        tag: { ...currentTag, aliases: nextAliases },
      };
    }

    const aliasesPropSchema = tagsDb?.properties?.[aliasesProp] || null;
    const aliasesPropertyValue =
      aliasesPropSchema?.type === "multi_select" ? notionMultiSelect(nextAliases) : notionRichText(nextAliases.join(", "));

    const patchRes = await notionFetch(env, `/pages/${tagId}`, {
      method: "PATCH",
      body: JSON.stringify({
        properties: {
          [aliasesProp]: aliasesPropertyValue,
        },
      }),
    });
    if (!patchRes.ok) {
      return { ok: false, error: "failed to update tag aliases", detail: patchRes.data };
    }

    const nextPage = patchRes.data && typeof patchRes.data === "object" ? patchRes.data : page;
    return {
      ok: true,
      tag: buildTagResponseFromPage(nextPage),
    };
  };

  const directTagId = asString(payload.id).trim();
  const bulkParentIds = uniqueIds(Array.isArray(payload.parentIds) ? payload.parentIds : []).filter(Boolean);
  const bulkChildIds = uniqueIds(Array.isArray(payload.childIds) ? payload.childIds : []).filter(Boolean);
  const hasBulkRelationUpdate = bulkParentIds.length > 0 || bulkChildIds.length > 0;
  if (!directTagId && hasBulkRelationUpdate) {
    if (bulkParentIds.length === 0 || bulkChildIds.length === 0) return badRequest("missing parentIds or childIds");

    const overlap = bulkParentIds.filter((id) => bulkChildIds.includes(id));
    if (overlap.length > 0) return badRequest("parentIds and childIds must be disjoint");

    const updatedChildren = [];
    for (const childId of bulkChildIds) {
      const updatedChild = await patchTagRelations({
        id: childId,
        addParentIds: bulkParentIds,
      });
      if (!updatedChild.ok) {
        return jsonResponse(
          { ok: false, error: updatedChild.error || "failed to update child tag relation", detail: updatedChild.detail || null },
          500,
        );
      }
      updatedChildren.push(updatedChild.tag);
    }

    const updatedParents = [];
    if (childrenProp) {
      for (const parentId of bulkParentIds) {
        const updatedParent = await patchTagRelations({
          id: parentId,
          addChildIds: bulkChildIds,
        });
        if (!updatedParent.ok) {
          return jsonResponse(
            { ok: false, error: updatedParent.error || "failed to update parent tag relation", detail: updatedParent.detail || null },
            500,
          );
        }
        updatedParents.push(updatedParent.tag);
      }
    }

    return okResponse(
      await withTagsIndex({
        parent_ids: bulkParentIds,
        child_ids: bulkChildIds,
        parents: updatedParents,
        children: updatedChildren,
      }),
    );
  }
  if (directTagId) {
    const addParentIds = Array.isArray(payload.addParentIds) ? payload.addParentIds : [];
    const addChildIds = Array.isArray(payload.addChildIds) ? payload.addChildIds : [];
    const hasRelationUpdate = addParentIds.length > 0 || addChildIds.length > 0;
    const hasAliasesUpdate = Object.prototype.hasOwnProperty.call(payload, "aliases");
    if (!hasRelationUpdate && !hasAliasesUpdate) return badRequest("no updates");

    let latestTag = null;
    if (hasRelationUpdate) {
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
      latestTag = updated.tag;
    }

    if (hasAliasesUpdate) {
      const updatedAliases = await patchTagAliases({
        id: directTagId,
        aliases: payload.aliases,
      });
      if (!updatedAliases.ok) {
        return jsonResponse(
          { ok: false, error: updatedAliases.error || "failed to update tag aliases", detail: updatedAliases.detail || null },
          500,
        );
      }
      latestTag = updatedAliases.tag;
    }

    if (!latestTag) {
      const loaded = await loadTagPage(directTagId);
      if (!loaded.ok) {
        return jsonResponse({ ok: false, error: "failed to fetch tag page", detail: loaded.detail || null }, 500);
      }
      latestTag = buildTagResponseFromPage(loaded.page);
    }
    return okResponse(await withTagsIndex(latestTag));
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

  return okResponse(
    await withTagsIndex({
      parent: parentUpdated || { id: parentId, children: [] },
      child: childUpdated.tag,
    }),
  );
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

function safeDecodeUrlPath(pathname) {
  const raw = asString(pathname);
  if (!raw) return "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function extractR2KeyFromPublicUrl(rawUrl, baseUrl) {
  const urlText = asString(rawUrl).trim();
  const baseText = asString(baseUrl).trim();
  if (!urlText || !baseText) return "";

  let targetUrl;
  let publicBaseUrl;
  try {
    targetUrl = new URL(urlText);
    publicBaseUrl = new URL(baseText);
  } catch {
    return "";
  }

  if (targetUrl.origin !== publicBaseUrl.origin) return "";

  const basePath = safeDecodeUrlPath(publicBaseUrl.pathname).replace(/\/+$/, "");
  const targetPath = safeDecodeUrlPath(targetUrl.pathname).replace(/^\/+/, "");
  if (!targetPath) return "";

  if (!basePath) return targetPath;

  const normalizedBasePath = basePath.replace(/^\/+/, "");
  if (targetPath === normalizedBasePath) return "";
  if (!targetPath.startsWith(`${normalizedBasePath}/`)) return "";
  return targetPath.slice(normalizedBasePath.length + 1);
}

function collectRelatedR2Keys(imageKey) {
  const key = asString(imageKey).trim().replace(/^\/+/, "");
  if (!key) return [];

  const prefixes = ["photos/", "photos-light/", "images/", "images-light/"];
  let suffix = null;
  for (const prefix of prefixes) {
    if (!key.startsWith(prefix)) continue;
    suffix = key.slice(prefix.length);
    break;
  }
  if (!suffix) return [key];

  const out = new Set(prefixes.map((prefix) => `${prefix}${suffix}`));
  return Array.from(out.values());
}

function collectR2KeysFromImageUrls(imageUrls, baseUrl) {
  const keys = new Set();
  const urls = Array.isArray(imageUrls) ? imageUrls : [];
  for (const rawUrl of urls) {
    const key = extractR2KeyFromPublicUrl(rawUrl, baseUrl);
    if (!key) continue;
    collectRelatedR2Keys(key).forEach((entry) => keys.add(entry));
  }
  return Array.from(keys.values());
}

async function listR2KeysByPrefix(r2, prefix) {
  const targetPrefix = asString(prefix).trim();
  if (!r2 || !targetPrefix) return [];

  const keys = [];
  let cursor = undefined;
  while (true) {
    const listed = await r2.list({ prefix: targetPrefix, cursor, limit: 1000 });
    const objects = Array.isArray(listed?.objects) ? listed.objects : [];
    keys.push(...objects.map((obj) => asString(obj?.key).trim()).filter(Boolean));
    if (!listed?.truncated) break;
    const nextCursor = asString(listed?.cursor).trim();
    if (!nextCursor) break;
    cursor = nextCursor;
  }
  return uniqueIds(keys);
}

async function deleteR2KeysSafely(env, keysRaw) {
  if (!env.GALLERY_R2) return { deleted: 0, failed: 0, deletedKeys: [], failedKeys: uniqueIds(keysRaw) };

  const keys = uniqueIds(Array.isArray(keysRaw) ? keysRaw : []);
  if (keys.length === 0) return { deleted: 0, failed: 0, deletedKeys: [], failedKeys: [] };

  const results = await Promise.all(
    keys.map(async (key) => {
      try {
        await env.GALLERY_R2.delete(key);
        return { key, ok: true };
      } catch {
        return { key, ok: false };
      }
    }),
  );

  const deletedKeys = results.filter((entry) => entry.ok).map((entry) => entry.key);
  const failedKeys = results.filter((entry) => !entry.ok).map((entry) => entry.key);
  return {
    deleted: deletedKeys.length,
    failed: failedKeys.length,
    deletedKeys,
    failedKeys,
  };
}

async function fetchWorkPage(env, workId) {
  const res = await notionFetch(env, `/pages/${workId}`, { method: "GET" });
  if (!res.ok) return null;
  return res.data;
}

async function handleCurationDeleteImages(request, env) {
  const worksProps = getWorksProps(env);

  const payload = await readJson(request);
  if (!payload || typeof payload !== "object") return badRequest("invalid json");

  const workId = asString(payload.workId).trim();
  const imageUrls = uniqueIds(Array.isArray(payload.imageUrls) ? payload.imageUrls : []);
  const archiveIfEmpty = payload.archiveIfEmpty !== false;
  if (!workId || imageUrls.length === 0) return badRequest("missing params");

  const workPage = await fetchWorkPage(env, workId);
  if (!workPage) return jsonResponse({ ok: false, error: "work not found" }, 404);
  const work = simplifyWorkFromNotionPage(env, workPage);

  const selected = work.images.filter((img) => imageUrls.includes(asString(img?.url).trim()));
  if (selected.length === 0) return badRequest("no matching images");
  const remaining = work.images.filter((img) => !imageUrls.includes(asString(img?.url).trim()));

  const updateRes = await notionFetch(env, `/pages/${workId}`, {
    method: "PATCH",
    body: JSON.stringify({
      properties: {
        [worksProps.images || "画像"]: notionExternalFiles(remaining),
      },
    }),
  });
  if (!updateRes.ok) {
    return jsonResponse({ ok: false, error: "failed to update work images", detail: updateRes.data }, 500);
  }

  let archived = false;
  if (archiveIfEmpty && remaining.length === 0) {
    const archiveRes = await notionFetch(env, `/pages/${workId}`, {
      method: "PATCH",
      body: JSON.stringify({ archived: true }),
    });
    if (!archiveRes.ok) {
      return jsonResponse({ ok: false, error: "failed to archive empty work", detail: archiveRes.data }, 500);
    }
    archived = true;
  }

  const baseUrl = getEnvString(env, "R2_PUBLIC_BASE_URL");
  const selectedUrls = selected.map((img) => asString(img?.url).trim()).filter(Boolean);
  const keysFromImages = collectR2KeysFromImageUrls(selectedUrls, baseUrl);
  const thumbKeys = await listR2KeysByPrefix(env.GALLERY_R2, `thumbs/${workId}-`);
  const deletedR2 = await deleteR2KeysSafely(env, [...keysFromImages, ...thumbKeys]);

  if (archived) {
    await clearUploadNotificationTrackingForWork(env, workId);
  }

  return okResponse({
    workId,
    removedImages: selected.length,
    remainingImages: remaining.length,
    archived,
    r2Deleted: deletedR2.deleted,
    r2Failed: deletedR2.failed,
    r2FailedKeys: deletedR2.failedKeys,
  });
}

async function handleCurationDeleteWork(request, env) {
  const payload = await readJson(request);
  if (!payload || typeof payload !== "object") return badRequest("invalid json");

  const workId = asString(payload.workId).trim();
  const deleteR2 = payload.deleteR2 !== false;
  if (!workId) return badRequest("missing workId");

  const workPage = await fetchWorkPage(env, workId);
  if (!workPage) return jsonResponse({ ok: false, error: "work not found" }, 404);
  const work = simplifyWorkFromNotionPage(env, workPage);

  const archiveRes = await notionFetch(env, `/pages/${workId}`, {
    method: "PATCH",
    body: JSON.stringify({ archived: true }),
  });
  if (!archiveRes.ok) {
    return jsonResponse({ ok: false, error: "failed to archive work", detail: archiveRes.data }, 500);
  }

  let r2Deleted = { deleted: 0, failed: 0, failedKeys: [] };
  if (deleteR2) {
    const baseUrl = getEnvString(env, "R2_PUBLIC_BASE_URL");
    const imageUrls = work.images.map((img) => asString(img?.url).trim()).filter(Boolean);
    const keysFromImages = collectR2KeysFromImageUrls(imageUrls, baseUrl);
    const thumbKeys = await listR2KeysByPrefix(env.GALLERY_R2, `thumbs/${workId}-`);
    r2Deleted = await deleteR2KeysSafely(env, [...keysFromImages, ...thumbKeys]);
  }

  await clearUploadNotificationTrackingForWork(env, workId);

  return okResponse({
    workId,
    archived: true,
    removedImages: work.images.length,
    r2Deleted: r2Deleted.deleted,
    r2Failed: r2Deleted.failed,
    r2FailedKeys: r2Deleted.failedKeys,
  });
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
    const archiveRes = await notionFetch(env, `/pages/${sourceWorkId}`, {
      method: "PATCH",
      body: JSON.stringify({ archived: true }),
    });
    if (archiveRes.ok) {
      await clearUploadNotificationTrackingForWork(env, sourceWorkId);
    }
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
    await Promise.all(sources.map(({ id }) => clearUploadNotificationTrackingForWork(env, id)));
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

async function regenerateTagsIndex(env) {
  const tagsDbId = getEnvString(env, "NOTION_TAGS_DB_ID");
  if (!env.GALLERY_R2) return { ok: false, error: "R2 binding not configured (GALLERY_R2)" };
  if (!tagsDbId) return { ok: false, error: "NOTION_TAGS_DB_ID not configured" };

  const tagsDbRes = await notionFetch(env, `/databases/${tagsDbId}`, { method: "GET" });
  if (!tagsDbRes.ok) {
    return { ok: false, error: "failed to fetch tags database", detail: tagsDbRes.data };
  }

  const queryRes = await queryAllDatabasePages(env, tagsDbId);
  if (!queryRes.ok) {
    return { ok: false, error: "failed to query tags database", detail: queryRes.data };
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

  return {
    ok: true,
    key,
    count: index.tags.length,
    generated_at: index.generated_at,
  };
}

async function refreshTagsIndexAfterTagMutation(env) {
  const result = await regenerateTagsIndex(env);
  if (result.ok) {
    return {
      regenerated: true,
      key: result.key,
      count: result.count,
      generated_at: result.generated_at,
    };
  }

  console.error("failed to regenerate tags index after tag mutation", {
    error: result.error,
    detail: result.detail || null,
  });
  return {
    regenerated: false,
    error: result.error,
  };
}

async function handleTriggerTagsIndexUpdate(request, env) {
  const result = await regenerateTagsIndex(env);
  if (!result.ok) {
    return jsonResponse(
      {
        ok: false,
        error: result.error,
        detail: result.detail || null,
      },
      500,
    );
  }

  return okResponse({
    message: "tags index regenerated",
    key: result.key,
    count: result.count,
    generated_at: result.generated_at,
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

function getFirstEnvString(env, keys) {
  for (const key of keys) {
    const value = getEnvString(env, key);
    if (value) return value;
  }
  return "";
}

async function handleJsonIndexPush(request, env, options) {
  if (!env.GALLERY_R2) return serverError("R2 binding not configured (GALLERY_R2)");

  const expectedToken = getFirstEnvString(env, options.tokenEnvKeys);
  if (!expectedToken) {
    return serverError(`${options.tokenEnvKeys[0]} not configured`);
  }

  const actualToken = getBearerToken(request);
  if (!actualToken || !timingSafeEqual(actualToken, expectedToken)) {
    return jsonResponse({ ok: false, error: "unauthorized" }, 401);
  }

  const payload = await readJson(request);
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return badRequest("invalid json");
  }

  const key = getEnvString(env, options.keyEnvName, options.defaultKey);
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

async function handleParticipantsIndexPush(request, env) {
  return handleJsonIndexPush(request, env, {
    tokenEnvKeys: ["UPLOAD_UI_PARTICIPANTS_INDEX_PUSH_TOKEN", "PARTICIPANTS_INDEX_PUSH_TOKEN"],
    keyEnvName: "PARTICIPANTS_INDEX_KEY",
    defaultKey: "participants_index.json",
  });
}

async function handleScheduleIndexPush(request, env) {
  return handleJsonIndexPush(request, env, {
    tokenEnvKeys: [
      "UPLOAD_UI_SCHEDULE_INDEX_PUSH_TOKEN",
      "SCHEDULE_INDEX_PUSH_TOKEN",
      "UPLOAD_UI_PARTICIPANTS_INDEX_PUSH_TOKEN",
      "PARTICIPANTS_INDEX_PUSH_TOKEN",
    ],
    keyEnvName: "SCHEDULE_INDEX_KEY",
    defaultKey: "schedule_index.json",
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

    if (pathname === "/schedule-index" && request.method === "GET") {
      return handleProxyJson(env, "SCHEDULE_INDEX_URL", "SCHEDULE_INDEX_KEY", "schedule_index.json");
    }

    if (pathname === "/schedule-index" && request.method === "POST") {
      return handleScheduleIndexPush(request, env);
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

    if (pathname === "/admin/notify/students-after-gallery-update" && request.method === "POST") {
      return handleNotifyStudentsAfterGalleryUpdate(env);
    }

    if (pathname === "/admin/curation/work-sync-status" && request.method === "POST") {
      return handleAdminCurationWorkSyncStatus(request, env);
    }

    if (pathname === "/admin/curation/delete-images" && request.method === "POST") {
      return handleCurationDeleteImages(request, env);
    }

    if (pathname === "/admin/curation/delete-work" && request.method === "POST") {
      return handleCurationDeleteWork(request, env);
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
