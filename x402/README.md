# x402 Micropayments Integration

The oracle sells its premium data feed via the **[x402 payment protocol](https://x402.org)** on Casper.
A consumer pays a CEP-18 token per request; a facilitator settles the payment on-chain (a
`transfer_with_authorization` CEP-18 transfer) before the data is returned — a closed agent-economy loop.

Built on the official **[make-software/casper-x402](https://github.com/make-software/casper-x402)**
facilitator. This folder documents how we wire it to our oracle.

## On-chain artifacts (Casper Testnet)

| | |
|---|---|
| CEP-18 payment token (package hash) | `8c5535f6f005c6e47d54372c22eb9af6fcb8e21e098f49af7b9e88123dd07a61` |
| Payee (data seller / oracle account hash) | `00b2d65e6edfb394f915ca7f22c39398933dd21d3ab15b2282a62768b19c5016c0` |
| Network | `casper:casper-test` · node `https://node.testnet.casper.network/rpc` |

The CEP-18 x402 token was installed from the `Cep18X402.wasm` shipped in the upstream repo, with
`name="Casper X402 Token"`, `symbol="X402"`, `decimals=9`.

## Components & flow

```
consumer → GET /oracle ──(402 Payment Required)──▶ resource server (:4021)
consumer signs EIP-712 transfer_with_authorization
consumer → GET /oracle + PAYMENT-SIGNATURE ──────▶ resource server
                                                    └─▶ facilitator (:4022) /settle
                                                          └─▶ on-chain CEP-18 transfer (Casper)
resource server ◀── data returned after settlement
```

## Setup

### 1. Clone the official facilitator

```bash
git clone https://github.com/make-software/casper-x402 /tmp/casper-x402
```

### 2. Apply our modifications

We changed the demo resource server to serve **our oracle data** instead of weather, and pointed the
client at `/oracle`:

- `examples/server/main.go` — route `GET /weather` → `GET /oracle`; the handler returns
  `web/oracle_state.json` (written by our agent each cycle).
- `examples/client/main.go` — request path `/weather?city=…` → `/oracle`.

See [`server-oracle-handler.go.txt`](server-oracle-handler.go.txt) for the exact handler snippet.

### 3. Run the facilitator (with a dedicated, funded key)

```bash
cd /tmp/casper-x402
CASPER_NETWORKS=casper:casper-test \
SECRET_KEY_PEM_CASPER_CASPER_TEST="$(cat <your-facilitator-key>/secret_key.pem)" \
SECRET_KEY_ALGO_CASPER_CASPER_TEST=ed25519 \
RPCURL_CASPER_CASPER_TEST=https://node.testnet.casper.network/rpc \
go run ./apps/facilitator        # :4022 — pays settlement gas
```

### 4. Run the resource server

```bash
cd /tmp/casper-x402
PAYEE_ADDRESS=00b2d65e6edfb394f915ca7f22c39398933dd21d3ab15b2282a62768b19c5016c0 \
FACILITATOR_URL=http://localhost:4022 \
CAIP2_CHAIN_ID=casper:casper-test \
ASSET_PACKAGE=8c5535f6f005c6e47d54372c22eb9af6fcb8e21e098f49af7b9e88123dd07a61 \
ASSET_NAME="Casper X402 Token" \
go run ./examples/server          # :4021 — x402-gated /oracle
```

### 5. Buy the data

- **Dashboard button** — the web dashboard's "Premium Data · x402" button calls our backend
  (`web/server.py` → `/api/x402-buy`), which runs the buyer client to pay and fetch the data.
- **Headless** — `go run ./examples/client` with a buyer key holding X402 tokens.

## A note on the "app-pays" model

The browser path (CSPR.click `signTypedData`) requires an **EIP-712-capable wallet** (MetaMask snap /
web3auth). **Casper Wallet does not support `signTypedData`**, so the dashboard's buy button pays from a
pre-funded **application buyer account** via the backend instead of the visitor's wallet.

This is intentional and arguably more on-narrative: in an agent economy, the **consuming application/agent
pays automatically** — machine-to-machine — rather than prompting a human to sign every micropayment.
