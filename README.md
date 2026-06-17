# Casper RWA Oracle · Autonomous Multi-Agent Network

> A network of autonomous AI agents that fetch real-world asset data from multiple independent sources, **cross-validate it with LLMs**, post it on-chain to a Casper smart contract with a per-feed **reputation score**, and **sell it via x402 micropayments** — a complete trust-minimized, self-sustaining RWA oracle and agent economy.
>
> **Submission for the Casper Agentic Buildathon 2026.**

---

## The Problem

On-chain apps need real-world data (gold, FX, crypto), but a single source can be wrong, delayed, or manipulated — and a naive oracle just copies it on-chain with no judgment. There's no measure of *how much to trust* a data point, no autonomous quality control, and no sustainable way for the oracle to pay for itself.

## What It Does

This project turns a passive data relay into an **autonomous, self-sustaining oracle network**:

1. **Multi-source fetch** — every asset is pulled from **2 independent public sources**.
2. **Multi-agent AI validation** — three independent LLM agents collaborate:
   - **Coordinator Agent** autonomously orchestrates the workflow via LLM tool-calling.
   - **Judge Agent** cross-validates the sources → consensus value + **confidence (0–100)**.
   - **Risk Agent** assesses anomalies → decides each feed's **reputation** reward/penalty.
3. **On-chain** — reliable data + confidence is written to the `RwaOracle` Casper contract, which tracks a **per-asset reputation score** that grows as a feed proves accurate.
4. **x402 monetization** — data consumers pay **per request via x402 micropayments** (CEP-18 token, settled on-chain). The oracle sells its own data — a closed **agent economy loop**.

Every data point carries an LLM-reasoned, multi-source confidence — and the whole pipeline runs itself.

## Architecture

```
  Independent data sources (2 per asset)
  Gold: gold-api + CoinGecko PAXG  |  BTC: Coinbase + CoinGecko  |  EUR/USD: Frankfurter + ER-API
                         │ fetch
                         ▼
  ┌──────────── Multi-Agent System (Python + DeepSeek LLM) ─────────────┐
  │  Coordinator Agent — LLM tool-calling, autonomously decides the flow │
  │      ├─ Judge Agent  (LLM)  cross-validate sources → confidence      │
  │      └─ Risk Agent   (LLM)  anomaly check → reputation decision      │
  └──────────────────────────┬──────────────────────────────────────────┘
              submit / score  │ (on-chain transactions)
                              ▼
  ┌──────────────────────────────────────┐     ┌────────────────────────┐
  │  RwaOracle contract  (Rust / Odra)    │────▶│  Web Dashboard (free)   │
  │  multi-asset · per-asset reputation    │     │  live feed + on-chain   │
  │  deployed on Casper Testnet            │     │  proof + AI reasoning   │
  └──────────────────────────┬───────────┘     └────────────────────────┘
                             │ premium data
                             ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  x402 paid API — consumers pay CEP-18 tokens per request,     │
  │  facilitator settles on-chain  →  agent economy loop          │
  └─────────────────────────────────────────────────────────────┘
```

## Live on Casper Testnet ✅

Everything below is **deployed and producing real on-chain transactions**:

| | |
|---|---|
| **RwaOracle contract** | `hash-e3b98aa54d9a7afb009a3ed99b60826a790cf850c5cf4991483775e057ba7d8f` |
| **X402 payment token (CEP-18)** | `hash-8c5535f6f005c6e47d54372c22eb9af6fcb8e21e098f49af7b9e88123dd07a61` |
| Contract deploy | [`71da1531…20e807`](https://testnet.cspr.live/transaction/71da153125e7160975d8eda86cf1324e67b2850cccfabc8f46d153f53620e807) |
| Agent data submit | [`5ed84998…f3d0927`](https://testnet.cspr.live/transaction/5ed84998b2106073f6e0368d01869a0e6faab7199f6e2a76273b8d515f3d0927) |
| Reputation update | [`1d0d8525…44faf3b9`](https://testnet.cspr.live/transaction/1d0d8525dc551716232e16fa6d622f64c010951615bf707b188ea00044faf3b9) |
| **x402 settlement (CEP-18 transfer)** | [`eb93df7d…1bc8affb`](https://testnet.cspr.live/transaction/eb93df7dd3470c7639199ee7e1c2152b21889c26a094b071b4b15c2d1bc8affb) |

## The Multi-Agent System

Three independent LLM agents (DeepSeek) divide the labor — this is the **"Agentic AI"** core:

| Agent | Role |
|---|---|
| **Coordinator** (`coordinator.py`) | Given the goal "keep the on-chain feed fresh and trustworthy," it uses **LLM function-calling** to autonomously decide which tools to call, in what order, whether to skip unreliable data, and when to reward/penalize a feed. Control flow is model-driven, not hard-coded. |
| **Judge** (`judge.py`) | Cross-validates the multiple source prices and outputs a consensus value, a 0–100 confidence, and a reason. Sources that agree → high confidence; an outlier → flagged. |
| **Risk** (`risk.py`) | A second opinion focused on reputation management — decides whether the feed earned a reputation reward and assigns a risk level. |

The Coordinator runs single-cycle, in an autonomous loop (`--loop`), or quick-demo mode (`--quick`).

## Smart Contract: `RwaOracle` (v2)

| Entry point | Description |
|---|---|
| `submit_data(asset, value, confidence, source_count)` | Authorized agent submits a data point (auto-registers new assets) |
| `get_data` / `get_reputation` / `get_asset_at` / `get_total_submissions` | Read feed data, per-asset reputation, the asset registry |
| `verify_and_score(asset, accurate)` | Owner adjusts a feed's reputation based on accuracy |
| `set_oracle_agent` | Owner rotates the authorized agent |

Per-asset reputation, an enumerable asset registry, and `owner` + `oracle_agent` access control. Fully unit-tested (7 tests).

## x402 Micropayments (Agent Economy)

The oracle **sells its data feed via the [x402 protocol](https://x402.org)** on Casper:

- A consumer requests the premium data endpoint → `402 Payment Required`.
- The consumer signs an **EIP-712 `transfer_with_authorization`** of a CEP-18 token.
- A **facilitator** verifies and **settles the payment on-chain** (CEP-18 transfer to the oracle).
- The data is returned.

This makes the oracle self-sustaining: machines pay machines for data. See [`x402/README.md`](x402/README.md) for the full setup. Built on the official [make-software/casper-x402](https://github.com/make-software/casper-x402) facilitator.

## Tech Stack

- **Smart contract:** Rust + [Odra 2.8](https://odra.dev/), deployed via `odra-casper-livenet-env`
- **Agents:** Python — multi-source fetcher, three LLM agents, on-chain submitter
- **LLM:** [DeepSeek](https://platform.deepseek.com/) (`deepseek-v4-flash`, OpenAI-compatible, function-calling)
- **Dashboard / API:** FastAPI + a live web dashboard
- **Payments:** x402 + a CEP-18 token, facilitator settling on Casper Testnet

## Repository Layout

```
contract/   Rust / Odra smart contract
  src/rwa_oracle.rs    RwaOracle v2 (multi-asset + per-asset reputation) + tests
  bin/                 deploy / submit / score (Odra livenet)
agent/      Python multi-agent system
  fetcher.py           multi-asset, multi-source price fetcher
  judge.py             Judge Agent  (LLM cross-validation)
  risk.py              Risk Agent   (LLM reputation decisions)
  coordinator.py       Coordinator  (LLM tool-calling orchestration)
  main.py              entry (--quick / --loop)
web/        FastAPI dashboard + x402 paid-data endpoint
x402/       x402 integration guide + config
```

## Getting Started

### 1. Smart contract

```bash
cd contract
cargo odra test                          # 7 unit tests
cargo odra build                         # build wasm
cargo run --bin deploy --features livenet  # deploy to testnet (configure contract/.env)
```

### 2. Multi-agent system

```bash
cd agent
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env       # set DEEPSEEK_API_KEY and CONTRACT_HASH
venv/bin/python main.py --quick    # one asset, full agentic cycle
venv/bin/python main.py            # all assets
```

### 3. Dashboard

```bash
cd web
../agent/venv/bin/pip install -r requirements.txt
../agent/venv/bin/uvicorn server:app --port 4020   # open http://localhost:4020
```

### 4. x402 paid data — see [`x402/README.md`](x402/README.md)

## Casper Agentic Buildathon

Built at the convergence of **Agentic AI**, **DeFi/RWA**, and the **Casper AI Toolkit** — autonomous agents that reason about real-world data, act on-chain, and transact via x402. Aligned with [Casper's AI Toolkit](https://www.casper.network/ai) direction.

## License

MIT
