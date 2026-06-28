const VALID_CITIES = new Set(["all", "agadir", "ifrane", "targa", "martil", "mazagan", "saidia"]);
const VALID_BREAKFAST = new Set(["any", "with", "without"]);

function json(res, status, payload) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(payload));
}

function valueToString(value, fallback = "") {
  if (value === undefined || value === null) return fallback;
  return String(value).trim();
}

function isDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

async function getBody(req) {
  if (req.body && typeof req.body === "object") return req.body;

  if (typeof req.body === "string") {
    try {
      return JSON.parse(req.body);
    } catch {
      return {};
    }
  }

  let raw = "";
  for await (const chunk of req) {
    raw += chunk;
  }

  if (!raw) return {};

  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function normalizeCities(raw) {
  const text = valueToString(raw, "all").toLowerCase();
  const tokens = text
    .replaceAll(";", ",")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  if (!tokens.length) return "all";
  if (tokens.includes("all")) return "all";

  const selected = tokens.filter((city) => VALID_CITIES.has(city) && city !== "all");

  if (!selected.length) {
    throw new Error(`Invalid cities value: ${text}`);
  }

  return [...new Set(selected)].join(",");
}

function normalizeStayLengths(raw) {
  const text = valueToString(raw, "3,4");
  const nights = text
    .replaceAll(";", ",")
    .split(",")
    .map((item) => Number.parseInt(item.trim(), 10))
    .filter((n) => Number.isInteger(n) && n >= 1 && n <= 30);

  if (!nights.length) {
    throw new Error("stay_lengths must contain at least one number from 1 to 30");
  }

  return [...new Set(nights)].join(",");
}

export default async function handler(req, res) {
  try {
    if (req.method === "GET") {
      return json(res, 200, {
        ok: true,
        route: "/api/scan",
        method: "GET",
        env: {
          APP_PIN: Boolean(process.env.APP_PIN),
          GH_OWNER: Boolean(process.env.GH_OWNER),
          GH_REPO: Boolean(process.env.GH_REPO),
          GH_REF: Boolean(process.env.GH_REF),
          GH_WORKFLOW_TOKEN: Boolean(process.env.GH_WORKFLOW_TOKEN),
        },
      });
    }

    if (req.method !== "POST") {
      return json(res, 405, { error: "Method not allowed" });
    }

    const body = await getBody(req);

    const missingEnv = ["APP_PIN", "GH_OWNER", "GH_REPO", "GH_WORKFLOW_TOKEN"].filter(
      (name) => !process.env[name]
    );

    if (missingEnv.length) {
      return json(res, 500, {
        error: "Missing Vercel environment variables",
        missing: missingEnv,
      });
    }

    const pin = valueToString(body.pin);

    if (pin !== valueToString(process.env.APP_PIN)) {
      return json(res, 401, { error: "Invalid PIN" });
    }

    const startDate = valueToString(body.start_date);
    const endDate = valueToString(body.end_date);

    if (!isDate(startDate) || !isDate(endDate)) {
      return json(res, 400, { error: "start_date and end_date must be YYYY-MM-DD" });
    }

    const cities = normalizeCities(body.cities);
    const stayLengths = normalizeStayLengths(body.stay_lengths);
    const maxPrice = valueToString(body.max_price, "350");
    const roomFilter = valueToString(body.room_filter);
    const minRemaining = valueToString(body.min_remaining);
    const breakfastFilter = valueToString(body.breakfast_filter, "any").toLowerCase();
    const dryRun = body.dry_run === true || valueToString(body.dry_run).toLowerCase() === "true";

    if (!VALID_BREAKFAST.has(breakfastFilter)) {
      return json(res, 400, { error: "breakfast_filter must be any, with, or without" });
    }

    const inputs = {
      start_date: startDate,
      end_date: endDate,
      cities,
      stay_lengths: stayLengths,
      max_price: maxPrice,
      room_filter: roomFilter,
      min_remaining: minRemaining,
      breakfast_filter: breakfastFilter,
      dry_run: dryRun ? "true" : "false",
    };

    const owner = valueToString(process.env.GH_OWNER);
    const repo = valueToString(process.env.GH_REPO);
    const ref = valueToString(process.env.GH_REF, "main");
    const workflow = "manual-zephyr-search.yml";

    const response = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${process.env.GH_WORKFLOW_TOKEN}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "zephyr-search-ui",
        },
        body: JSON.stringify({
          ref,
          inputs,
        }),
      }
    );

    const detail = await response.text();

    if (!response.ok) {
      return json(res, response.status, {
        error: "GitHub workflow dispatch failed",
        status: response.status,
        detail,
        inputs,
        hint: "Check GH_OWNER, GH_REPO, GH_REF, GH_WORKFLOW_TOKEN, token repository access, and Actions read/write permission.",
      });
    }

    return json(res, 200, {
      ok: true,
      message: "Search started. Check GitHub Actions and Telegram.",
      inputs,
    });
  } catch (error) {
    console.error("[api/scan]", error);
    return json(res, 500, {
      error: "Vercel scan API crashed",
      message: error && error.message ? error.message : String(error),
    });
  }
}
