import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const CITY_OPTIONS = [
  { key: "agadir", label: "Agadir" },
  { key: "ifrane", label: "Ifrane" },
  { key: "targa", label: "Targa" },
  { key: "martil", label: "Martil" },
  { key: "mazagan", label: "Mazagan" },
  { key: "saidia", label: "Saïdia" },
];

function todayIso() {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  return new Date(now.getTime() - offset * 60_000).toISOString().slice(0, 10);
}

function plusDaysIso(days) {
  const now = new Date();
  now.setDate(now.getDate() + days);
  const offset = now.getTimezoneOffset();
  return new Date(now.getTime() - offset * 60_000).toISOString().slice(0, 10);
}

function App() {
  const [pin, setPin] = useState("");
  const [startDate, setStartDate] = useState(todayIso());
  const [endDate, setEndDate] = useState(plusDaysIso(30));
  const [selectedCities, setSelectedCities] = useState(["agadir"]);
  const [stayLengths, setStayLengths] = useState("3,4");
  const [maxPrice, setMaxPrice] = useState("350");
  const [roomFilter, setRoomFilter] = useState("");
  const [minRemaining, setMinRemaining] = useState("");
  const [breakfastFilter, setBreakfastFilter] = useState("any");
  const [dryRun, setDryRun] = useState("false");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const citiesValue = useMemo(() => selectedCities.join(","), [selectedCities]);

  function toggleCity(cityKey) {
    setSelectedCities((current) => {
      if (current.includes(cityKey)) {
        return current.filter((item) => item !== cityKey);
      }
      return [...current, cityKey];
    });
  }

  function selectAllCities() {
    setSelectedCities(CITY_OPTIONS.map((city) => city.key));
  }

  function clearCities() {
    setSelectedCities([]);
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setResult(null);

    try {
      const response = await fetch("/api/scan", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          pin,
          start_date: startDate,
          end_date: endDate,
          cities: citiesValue || "all",
          stay_lengths: stayLengths,
          max_price: maxPrice,
          room_filter: roomFilter,
          min_remaining: minRemaining,
          breakfast_filter: breakfastFilter,
          dry_run: dryRun,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        const parts = [
          data.error || "Request failed",
          data.status ? `Status: ${data.status}` : "",
          data.detail ? `Detail: ${data.detail}` : "",
          data.hint ? `Hint: ${data.hint}` : "",
        ].filter(Boolean);

        throw new Error(parts.join("\n\n"));
      }

      setResult({
        ok: true,
        message: data.message,
      });
    } catch (error) {
      setResult({
        ok: false,
        message: error.message,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">Private Zephyr Tool</p>
        <h1>Manual availability search</h1>
        <p className="sub">
          Choose the period, resorts, nights, and filters. The scan runs in GitHub Actions and sends a clean summary to Telegram.
        </p>
      </section>

      <form className="card" onSubmit={submit}>
        <div className="grid two">
          <label>
            Private app PIN
            <input type="password" value={pin} onChange={(e) => setPin(e.target.value)} required />
          </label>

          <label>
            Max price / night MAD
            <input type="number" min="1" value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} required />
          </label>
        </div>

        <div className="grid two">
          <label>
            Start date
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} required />
          </label>

          <label>
            End date
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} required />
          </label>
        </div>

        <div className="section-title">
          <span>Cities</span>
          <div className="mini-actions">
            <button type="button" onClick={selectAllCities}>All</button>
            <button type="button" onClick={clearCities}>Clear</button>
          </div>
        </div>

        <div className="cities">
          {CITY_OPTIONS.map((city) => (
            <label key={city.key} className={selectedCities.includes(city.key) ? "pill active" : "pill"}>
              <input type="checkbox" checked={selectedCities.includes(city.key)} onChange={() => toggleCity(city.key)} />
              {city.label}
            </label>
          ))}
        </div>

        <div className="grid two">
          <label>
            Stay lengths
            <input value={stayLengths} onChange={(e) => setStayLengths(e.target.value)} placeholder="3,4" required />
            <small>Comma-separated nights, example: 2,3,4</small>
          </label>

          <label>
            Breakfast filter
            <select value={breakfastFilter} onChange={(e) => setBreakfastFilter(e.target.value)}>
              <option value="any">Any</option>
              <option value="without">Without breakfast</option>
              <option value="with">With breakfast</option>
            </select>
          </label>
        </div>

        <div className="grid two">
          <label>
            Room text filter
            <input value={roomFilter} onChange={(e) => setRoomFilter(e.target.value)} placeholder="Twin, F1, Standard..." />
          </label>

          <label>
            Minimum remaining
            <input type="number" min="1" value={minRemaining} onChange={(e) => setMinRemaining(e.target.value)} placeholder="Optional" />
          </label>
        </div>

        <label>
          Dry run
          <select value={dryRun} onChange={(e) => setDryRun(e.target.value)}>
            <option value="false">Send Telegram message</option>
            <option value="true">Dry run only</option>
          </select>
        </label>

        <div className="summary">
          <b>Search summary</b>
          <span>{startDate} → {endDate}</span>
          <span>Cities: {citiesValue || "all"}</span>
          <span>Nights: {stayLengths}</span>
          <span>Max price: {maxPrice} MAD/night</span>
        </div>

        <button className="primary" type="submit" disabled={busy || selectedCities.length === 0}>
          {busy ? "Starting scan..." : "Start Telegram Search"}
        </button>
      </form>

      {result && (
        <section className={result.ok ? "notice success" : "notice error"}>
          <h2>{result.ok ? "Search started" : "Could not start search"}</h2>
          <p>{result.message}</p>
          {result.ok && <p className="hint">GitHub Actions is now running. Check Telegram when the scan finishes.</p>}
        </section>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
