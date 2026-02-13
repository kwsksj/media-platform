export function qs(selector, root = document) {
	return root.querySelector(selector);
}

export function qsa(selector, root = document) {
	return Array.from(root.querySelectorAll(selector));
}

export function el(tagName, attrs = {}, children = []) {
	const node = document.createElement(tagName);
	Object.entries(attrs || {}).forEach(([key, value]) => {
		if (value === null || value === undefined) return;
		if (key === "class") {
			node.className = String(value);
			return;
		}
		if (key === "text") {
			node.textContent = String(value);
			return;
		}
		if (key.startsWith("data-")) {
			node.setAttribute(key, String(value));
			return;
		}
		if (key === "html") {
			node.innerHTML = String(value);
			return;
		}
		node.setAttribute(key, String(value));
	});

	for (const child of Array.isArray(children) ? children : [children]) {
		if (child === null || child === undefined) continue;
		if (typeof child === "string") {
			node.appendChild(document.createTextNode(child));
			continue;
		}
		node.appendChild(child);
	}
	return node;
}

export function toHiragana(value) {
	const input = String(value || "");
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

export function normalizeSearch(value) {
	return toHiragana(String(value || "").toLowerCase().trim());
}

export function formatIso(iso) {
	if (!iso) return "";
	try {
		const date = new Date(iso);
		if (Number.isNaN(date.getTime())) return String(iso);
		return date.toLocaleString("ja-JP", { hour12: false });
	} catch {
		return String(iso);
	}
}

export function debounce(fn, waitMs = 200) {
	let timer = 0;
	return (...args) => {
		window.clearTimeout(timer);
		timer = window.setTimeout(() => fn(...args), waitMs);
	};
}

export function showToast(message, { root = null } = {}) {
	const toastRoot = root || document.getElementById("toast-root");
	if (!toastRoot) return;
	const toast = el("div", { class: "toast", text: message });
	toastRoot.appendChild(toast);
	window.setTimeout(() => {
		toast.remove();
	}, 3800);
}

