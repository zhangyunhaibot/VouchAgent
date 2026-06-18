// Vercel Serverless Function：把浏览器的 /api/rpc 转发到 Casper testnet 节点（解决浏览器 CORS）。
// 部署后前端 RpcClient 指向 location.origin + "/api/rpc"。零依赖（用 Node 18+ 内置 fetch）。
export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  try {
    const upstream = await fetch("https://node.testnet.casper.network/rpc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: typeof req.body === "string" ? req.body : JSON.stringify(req.body),
    });
    const data = await upstream.json();
    res.status(200).json(data);
  } catch (e) {
    res.status(502).json({ error: String((e && e.message) || e) });
  }
}
