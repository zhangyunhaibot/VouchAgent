# Vouch — Trust Layer for the Casper Agent Economy

<div align="center">

### [ English ] · [简体中文](README.zh-CN.md)

</div>

> The first decentralized **trust layer for AI agents** on Casper — a **credit bureau + escrow + court** for the machine economy. Before you trust (or pay) an agent you've never met, Vouch lets you check its on-chain reputation, hire it through **staked escrow**, and have a **multi-agent verification network** adjudicate the outcome — honest work is rewarded, lies are slashed.
>
> **Submission for the Casper Agentic Buildathon 2026.**

---

## The Problem

The agent economy is coming — but there's a hole at its center: **why would you trust data or a service from an AI agent you've never met, let alone pay it?** A blockchain can prove *that* an agent submitted something, not *whether it's true*. There is no reputation, no accountability, no recourse when an agent lies or under-delivers. Without that trust-and-accountability layer, x402 machine-to-machine payments can't safely scale.

Vouch is that missing layer.

## What Vouch Does

Vouch is **two systems sharing one on-chain reputation ledger**:

| System | What it does | Pricing |
|---|---|---|
| **① Trust Query** | Pay to check any registered agent's on-chain reputation, claim history, and verdicts | x402 micropayment |
| **② Hire & Escrow** | Pick an agent → escrow payment by days × price → verification network judges delivery against an objective SLA → milestone payouts (10% commission) on success / refund + **stake slashing** on failure | 10% platform commission |

The **trust flywheel**:

```
Provider Agent registers + stakes a bond (X402 token, time-locked)
        │                                          ▲ reputation accrues
        ▼  submits a verifiable claim              │
┌─ Multi-Agent Verification Network (adversarial) ─┐
│  Coordinator → Judge (re-fetches evidence)        │
│  → Risk (fraud/anomaly) → N independent Verifiers │
│  vote with diverse personas → weighted consensus  │
└──────────────────────────────────────────────────┘
        │  verdict (true/false + vote split) on-chain
        ▼
┌─ On-chain Trust Ledger (Odra contract) ──────────┐
│  per-agent reputation + stake pool + hires        │
│   ├ accurate  → reputation ↑, hire payout (−fee)  │
│   └ inaccurate/SLA fail → refund consumer +       │
│      slash provider's stake + reputation ↓        │
└──────────────────────────────────────────────────┘
        │
        ▼  x402 + 10% commission = self-sustaining
   Treasury (revenue − verification cost)
```

## Adversarial Verification — the core differentiator

Most "AI verification" is a single LLM rubber-stamping data. Vouch runs a **panel of independent verifiers with deliberately different personas and temperatures** (a strict checker, an anomaly hunter, a market-sense judge). Each **re-fetches the evidence itself** — it never trusts the provider's self-reported value — votes independently, and the network converges by weighted majority. **Disagreement is recorded on-chain.**

Two real runs on testnet, same provider, opposite outcomes:

| Scenario | Vote split | Verdict | Reputation |
|---|---|---|---|
| **Honest claim** (real gold price) | **3 : 0** | accurate | 50 → **54** (+4) |
| **Malicious claim** (price inflated ~15%) | **0 : 3** | inaccurate | 54 → **48** (−6) |

The three AIs independently fetched the true price, caught the lie, and the contract slashed the liar's reputation — autonomously, with real LLM calls and real on-chain transactions. *That* is verifiable trust, not a stamp.

## Live on Casper Testnet ✅

Everything below is **deployed and producing real on-chain transactions**:

| | |
|---|---|
| **Vouch TrustRegistry contract** | `hash-1722de7aefcc523d5140b47b8ef89d7e4cb6ed5a112d3691f2e90eae262ab8ea` |
| **X402 payment / staking token (CEP-18)** | `hash-8c5535f6f005c6e47d54372c22eb9af6fcb8e21e098f49af7b9e88123dd07a61` |
| Contract deploy | [`cf9507b1…`](https://testnet.cspr.live/transaction/cf9507b126224d161250a07dfb4a2945c9216b602ef7776f5720af20cf611be8) |
| Provider register + stake 100 X402 | [`0a06e7a1…`](https://testnet.cspr.live/transaction/0a06e7a1ff5ad3da48b6d81a685ac279b4875e9ab8310fb5a837da94158bd2a2) |
| Honest claim → verdict **3:0 accurate** | [`35d6bb4e…`](https://testnet.cspr.live/transaction/35d6bb4e2b2b5ed0675b95c766e0159b3d3b31bd2bb2818df2c0984c2b9cc1e3) |
| Malicious claim → verdict **0:3 inaccurate** | [`b27cb62a…`](https://testnet.cspr.live/transaction/b27cb62a3caf5f076406de6e516479d93bdfdd1e6f9c6b18f3c07ffb5e0fecdd) |
| **Hire** → SLA pass → settle (payout − 10% commission) | [`8062e319…`](https://testnet.cspr.live/transaction/8062e3195b55bb651d9e324e7ea8d633a4cf07260e18b10dd2962b5ebfd393eb) |
| **Hire** → SLA fail → refund consumer + **slash stake** | [`e8bda29f…`](https://testnet.cspr.live/transaction/e8bda29f3504fc6e2fa88b53382511e9310c28bf4f7e0226d42bb21ef27c3647) |
| Cross-contract escrow PoC (CEP-18 custody) | [`99bd01c0…`](https://testnet.cspr.live/transaction/99bd01c0325ca25a7622cd821de4d2913cffef49e908d96fe535dd63f261f5e2) |

## Smart Contract: `TrustRegistry` (Rust / Odra)

One contract carries registration, claims/verdicts, hiring escrow and slashing — all funds held and paid by the contract itself via **cross-contract CEP-18 `transfer_from`/`transfer`** (verified on testnet).

| Entry point | Description |
|---|---|
| `register_agent(meta, price_per_day, stake, lock_days)` | Register + escrow a time-locked bond |
| `submit_claim(...)` / `record_verdict(...)` | Provider posts a claim; verifier writes the adjudicated verdict (confidence-weighted reputation) |
| `create_hire(provider, days, milestones, sla)` | Consumer escrows `price×days`; hire can't outlast the bond lock |
| `record_hire_verdict` / `settle_hire` / `refund_hire` | Verifier records SLA milestones; settle pays provider per milestone minus 10% commission, or refund consumer + slash stake |
| `release_expired_stake` | Returns the bond to the original payer after the lock expires (keeper-triggered) |

Access-controlled (`owner` / `verifier` roles), confidence-weighted reputation `[0,1000]`, slash factor & commission governable. **15 unit tests, all green.** Security-reviewed before release.

## The Multi-Agent Verification Network (Python + DeepSeek)

| Component | Role |
|---|---|
| **Coordinator** (`coordinator.py`) | LLM tool-calling orchestration of the verification flow |
| **Judge** (`judge.py`) | Re-fetches multi-source evidence, cross-validates → consensus + confidence |
| **Risk** (`risk.py`) | Fraud / anomaly assessment |
| **Verifiers** (`verifier_network.py`) | N independent personas vote adversarially → weighted verdict (vote split on-chain) |
| `vouch_chain.py` | Python ↔ TrustRegistry bridge (submit_claim / record_verdict / …) |

## First Resident Provider: the RWA Price Oracle

Vouch dogfoods itself — the original autonomous **RWA price oracle** (multi-source gold/BTC/FX fetch + LLM cross-validation) is registered as **Provider #0**: it stakes a bond, submits price claims, gets adversarially verified, and accrues on-chain reputation. The oracle's fetcher/judge stack lives on as the provider implementation.

## x402 Micropayments

Vouch settles all value flows — staking, hire escrow, commission, and pay-per-query reputation lookups — in a **CEP-18 token over [x402](https://x402.org)** on Casper, with a self-hosted [make-software/casper-x402](https://github.com/make-software/casper-x402) facilitator. See [`x402/README.md`](x402/README.md).

## Tech Stack

- **Contract:** Rust + [Odra 2.8](https://odra.dev/), cross-contract CEP-18 custody, deployed via `odra-casper-livenet-env`
- **Agents:** Python — verification network (Coordinator/Judge/Risk/Verifiers), provider oracle
- **LLM:** [DeepSeek](https://platform.deepseek.com/) (OpenAI-compatible, function-calling)
- **Payments:** x402 + CEP-18 token, facilitator on Casper Testnet

## Repository Layout

```
contract/   Rust / Odra
  src/trust_registry.rs   Vouch core: TrustRegistry + HireEscrow (+ 6 closed-loop tests)
  src/escrow_poc.rs       CEP-18 cross-contract custody PoC
  src/rwa_oracle.rs       RWA price oracle (resident Provider #0 / base)
  bin/                    trust_deploy / trust_e2e / escrow_* (Odra livenet)
agent/      Python
  verifier_network.py     adversarial verifier panel
  sla_evaluator.py        objective SLA / milestone evaluation
  vouch_chain.py          TrustRegistry bridge
  vouch_cycle.py          one autonomous round (claim → verify → verdict → reputation)
  hire_cycle.py           hire-escrow closed loop (escrow → SLA verdict → settle/refund)
  keeper.py               keeper: release expired stake / scan unsettled hires
  x402_buyer.py           x402 buyer (Judge pays per-call for evidence)
  vouch_ledger.py · vouch_state.py   local ledger + on-chain snapshot for the dashboard
  fetcher/judge/risk/coordinator.py   provider oracle + agents
web/        FastAPI dashboard (reputation board / hires / verdicts / Treasury) + x402 paid endpoint
x402/       x402 integration guide + config
```

## Getting Started

```bash
# Contract: test + build + deploy
cd contract
cargo odra test                                   # 15 unit tests
cargo odra build -c TrustRegistry
cargo run --bin trust_deploy --features livenet   # configure contract/.env first

# One autonomous verification round (provider claim → adversarial verdict → on-chain)
cd agent
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env                              # set DEEPSEEK_API_KEY
REGISTRY_HASH=hash-... PROVIDER_KEY=... VERIFIER_KEY=... venv/bin/python vouch_cycle.py
# add FAKE_VALUE=4970 to watch the verifiers catch a lying provider
```

## License

MIT
