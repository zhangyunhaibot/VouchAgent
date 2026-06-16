# Casper RWA Oracle Agent

> An autonomous AI agent that fetches real-world asset data, **cross-validates it with an LLM**, and posts it on-chain to a Casper smart contract — building a trust-minimized RWA (Real-World Asset) oracle.
>
> **Submission for the Casper Agentic Buildathon 2026.**

---

## The Problem

On-chain applications need real-world data (gold prices, FX rates, equities), but a single data source can be wrong, delayed, or manipulated — and a naive oracle just copies it on-chain with no judgment. There is no built-in measure of *how much to trust* a given data point.

## What It Does

This agent turns a passive "data relay" into an **active data quality inspector**:

1. **Fetches** the same asset price from **multiple independent sources**.
2. **Cross-validates** them with an LLM — sources that agree → high confidence; an outlier → flagged and down-weighted.
3. **Posts** the consensus value plus a **0–100 confidence score** on-chain, and maintains an on-chain **reputation score** for the oracle agent that grows as its data proves accurate.

The result is an oracle where every data point carries an LLM-reasoned, multi-source confidence — not just a number.

## Architecture

```
   ┌──────────────────────────┐
   │  Independent data sources │   gold-api.com (XAU) · CoinGecko (PAX Gold)
   └────────────┬─────────────┘
                │ 1. fetch
                ▼
   ┌──────────────────────────┐
   │   LLM cross-validation    │   DeepSeek — agree? outlier? → consensus + confidence
   └────────────┬─────────────┘
                │ 2. judge (confidence 0–100)
                ▼
   ┌──────────────────────────┐
   │  Casper smart contract    │   RwaOracle — stores data point + reputation score
   │      (Rust / Odra)        │   deployed on Casper Testnet
   └────────────┬─────────────┘
                │ 3. on-chain transaction
                ▼
          verifiable on cspr.live
```

## Live on Casper Testnet ✅

The contract is **deployed and producing real on-chain transactions**:

| | |
|---|---|
| **Contract (package hash)** | `hash-37cc023989e5689fe47e264caeb46f24483feb2ecc513f7f4d2ec1de03267ebd` |
| **Network** | Casper Testnet (`casper-test`) |
| **Deploy transaction** | [`f1361d9f…31701b`](https://testnet.cspr.live/transaction/f1361d9fe2c219eb56b593e2753ba1941ba6bde8b92f3ed82bff33f7eb31701b) |
| **submit_data transaction** | [`e75e9eda…02a4e3`](https://testnet.cspr.live/transaction/e75e9edaa11935c4af2ccf48414a634579a9173484b06c86a44aa7dd3502a4e3) |
| **submit_data (via agent)** | [`0aff5b2b…f6419`](https://testnet.cspr.live/transaction/0aff5b2b2ce2c10c71a05f1ede61ce254a10853a00ff56f1441b69cba1af6419) |

## Smart Contract: `RwaOracle`

| Entry point | Description |
|---|---|
| `submit_data(asset, value, confidence)` | Authorized oracle agent submits a data point (produces an on-chain transaction) |
| `get_data(asset)` | Read the latest data point for an asset |
| `get_reputation()` | Read the oracle agent's reputation score |
| `verify_and_score(accurate)` | Owner adjusts reputation based on historical accuracy |
| `set_oracle_agent(new_agent)` | Owner rotates the authorized agent |

Access control: a contract `owner` plus an authorized `oracle_agent` — unauthorized calls revert. Fully unit-tested.

## Tech Stack

- **Smart contract:** Rust + [Odra 2.8](https://odra.dev/) framework, deployed via `odra-casper-livenet-env`
- **Agent:** Python — multi-source fetcher, LLM judge, on-chain submitter
- **LLM:** [DeepSeek](https://platform.deepseek.com/) (`deepseek-v4-flash`, OpenAI-compatible API) with JSON structured output
- **Chain:** Casper Testnet via the public node `https://node.testnet.casper.network`

## Repository Layout

```
contract/        Rust / Odra smart contract
  src/rwa_oracle.rs   RwaOracle module + unit tests
  bin/deploy.rs       deploy + first on-chain submit
  bin/submit.rs       submit one data point to the deployed contract
agent/           Python autonomous agent
  fetcher.py          multi-source price fetcher
  judge.py            LLM cross-validation (DeepSeek)
  chain.py            on-chain submission
  main.py             orchestrator (fetch → judge → submit)
```

## Getting Started

### 1. Smart contract

```bash
cd contract
cargo odra test            # run unit tests
cargo odra build           # build the wasm

# deploy to testnet (configure contract/.env first — see contract/.env)
cargo run --bin deploy --features livenet
```

`contract/.env`:

```
ODRA_CASPER_LIVENET_SECRET_KEY_PATH=keys/secret_key.pem
ODRA_CASPER_LIVENET_NODE_ADDRESS=https://node.testnet.casper.network
ODRA_CASPER_LIVENET_EVENTS_URL=https://node.testnet.casper.network/events
ODRA_CASPER_LIVENET_CHAIN_NAME=casper-test
```

### 2. Agent

```bash
cd agent
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env        # fill in DEEPSEEK_API_KEY and CONTRACT_HASH
venv/bin/python main.py     # one cycle: fetch → judge → submit on-chain
```

## Casper Agentic Buildathon

Built around the convergence of **Agentic AI**, **DeFi**, and **Real-World Assets** on Casper — an autonomous agent that reasons about real-world data and acts on-chain. Aligned with the Casper [AI Toolkit](https://www.casper.network/ai) direction (x402 micropayments, agentic on-chain actions).

## License

MIT
