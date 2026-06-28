export default function handler(req, res) {
  res.status(200).json({
    ok: true,
    service: "zephyr-search-ui",
    route: "/api/health",
    time: new Date().toISOString()
  });
}
