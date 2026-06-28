function cleanString(value, fallback = "") {
  if (value === undefined || value === null) return fallback;
  const text = String(value).trim();
  return text || fallback;
}

function isDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(cleanString(value));
}

function sanitizeCities(value) {
  const text = cleanString(value, "all").toLowerCase();
  const allowed = new Set(["all", "agadir", "ifrane", "targa", "martil", "mazagan", "saidia"]);
  const parts = text.split(",").map((item) => item.trim()).filter(Boolean);

  if (!parts.length) return "all";
  if (parts.includes("all")) return "all";

  for (const part of parts) {
    if (!allowed.has(part)) {
      throw new Error(`Invalid city: ${part}`);
    }
  }

  return parts.join(",");
}

function sanitizeStayLengths(value) {
  const text = cleanString(value, "3,4");
  const parts = text.split(",").map((item) => item.trim()).filter(Boolean);

  if (!parts.length) return "3,4";

  const numbers = parts.map((item) => {
    const num = Number(item);
    if (!Number.isInteger(num) || num < 1 || num > 30) {
      throw new Error("Stay lengths must be whole numbers between 1 and 30");
    }
    return String(num);
  });

  return [...new Set(numbers)].join(",");
}

function sanitizePositiveNumber(value, fallback) {
  const text = cleanString(value, fallback);
  const num = Number(text);

  if (!Number.isFinite(num) || num <= 0) {
    throw new Error("Max price must be a positive number");
  }

  return String(Math.round(num));
}

function sanitizeBreakfast(value) {
  const text = cleanString(value, "any").toLowerCase();

  if (!["any", "with", "without"].includes(text)) {
    throw new Error("Invalid breakfast filter");
  }

  return text;
}

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  try {
    const body = req.body || {};

    if (!process.env.APP_PIN || body.pin !== process.env.APP_PIN) {
      res.status(401).json({ error: "Invalid PIN" });
      return;
    }

    const owner = cleanString(process.env.GH_OWNER);
    const repo = cleanString(process.env.GH_REPO);
    const ref = cleanString(process.env.GH_REF, "main");
    const token = cleanString(process.env.GH_WORKFLOW_TOKEN);

    if (!owner || !repo || !token) {
      res.status(500).json({ error: "Missing Vercel environment variables" });
      return;
    }

    const startDate = cleanString(body.start_date);
    const endDate = cleanString(body.end_date);

    if (!isDate(startDate) || !isDate(endDate)) {
      res.status(400).json({ error: "Start date and end date must be YYYY-MM-DD" });
      return;
    }

    if (endDate < startDate) {
      res.status(400).json({ error: "End date must be after start date" });
      return;
    }

    const inputs = {
      start_date: startDate,
      end_date: endDate,
      cities: sanitizeCities(body.cities),
      stay_lengths: sanitizeStayLengths(body.stay_lengths),
      max_price: sanitizePositiveNumber(body.max_price, "350"),
      room_filter: cleanString(body.room_filter),
      min_remaining: cleanString(body.min_remaining),
      breakfast_filter: sanitizeBreakfast(body.breakfast_filter),
      dry_run: cleanString(body.dry_run, "false") === "true" ? "true" : "false",
    };

    if (inputs.min_remaining) {
      const minRemaining = Number(inputs.min_remaining);
      if (!Number.isInteger(minRemaining) || minRemaining < 1) {
        res.status(400).json({ error: "Minimum remaining must be a positive whole number" });
        return;
      }
    }

    const response = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/actions/workflows/manual-zephyr-search.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
          "User-Agent": "zephyr-search-ui",
        },
        body: JSON.stringify({ ref, inputs }),
      }
    );

    if (!response.ok) {
      const errorText = await response.text();
      res.status(response.status).json({
        error: "GitHub workflow dispatch failed",
        detail: errorText,
      });
      return;
    }

    res.status(200).json({
      ok: true,
      message: "Search started. Results will arrive in Telegram when GitHub Actions finishes.",
      inputs,
    });
  } catch (error) {
    res.status(500).json({ error: error.message || "Unexpected error" });
  }
}
