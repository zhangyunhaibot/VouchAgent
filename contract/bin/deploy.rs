//! 把 RwaOracle 合约部署到 Casper 测试网，并立即做一次 submit_data，
//! 产生一笔真实链上交易（满足黑客松「Testnet 上有产生交易的组件」硬要求）。
//!
//! 运行：在 contract/ 目录下，配好 .env 后执行
//!   cargo run --bin deploy --features livenet

use contract::rwa_oracle::{RwaOracle, RwaOracleInitArgs};
use odra::casper_types::U256;
use odra::host::Deployer;
use odra::prelude::Addressable;

fn main() {
    let env = odra_casper_livenet_env::env();

    // 部署账户既是合约 owner，也是授权的预言机 Agent。
    let oracle_agent = env.caller();

    // 部署合约（gas 单位为 motes，1 CSPR = 1e9 motes）。
    env.set_gas(400_000_000_000u64);
    let mut oracle = RwaOracle::deploy(&env, RwaOracleInitArgs { oracle_agent });
    println!("✅ RwaOracle 已部署");
    println!("   合约地址: {}", oracle.address().to_string());

    // 提交一条黄金价格数据，产生一笔链上交易。
    env.set_gas(10_000_000_000u64);
    oracle.submit_data(String::from("XAU/USD"), U256::from(4_330_000_000u64), 95);
    println!("✅ 已提交一条数据，链上交易完成");

    // 读回链上数据验证。
    let dp = oracle.get_data(String::from("XAU/USD"));
    println!("   链上读回: value={} confidence={}", dp.value, dp.confidence);
    println!("   信誉分: {}", oracle.get_reputation());
    println!("   提交次数: {}", oracle.get_submission_count());
}
