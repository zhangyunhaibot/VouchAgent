//! 调用 RwaOracle 的 verify_and_score 调整某资产信誉分（owner-only，供 Risk Agent 通过 Python 调用）。
//!
//! 环境变量：
//!   ORACLE_CONTRACT_HASH = hash-...
//!   SCORE_ASSET          = 资产标识
//!   SCORE_ACCURATE       = true / false（true→信誉分+1，false→-1）
//!
//! 运行：cargo run --bin score --features livenet

use std::env;
use std::str::FromStr;

use contract::rwa_oracle::RwaOracle;
use odra::host::HostRefLoader;
use odra::prelude::Address;

fn main() {
    let livenet = odra_casper_livenet_env::env();

    let contract_hash = env::var("ORACLE_CONTRACT_HASH").expect("缺少 ORACLE_CONTRACT_HASH");
    let address = Address::from_str(&contract_hash).expect("合约地址格式错误");
    let asset = env::var("SCORE_ASSET").expect("缺少 SCORE_ASSET");
    let accurate: bool = env::var("SCORE_ACCURATE")
        .expect("缺少 SCORE_ACCURATE")
        .parse()
        .expect("SCORE_ACCURATE 必须是 true/false");

    let mut oracle = RwaOracle::load(&livenet, address);
    livenet.set_gas(10_000_000_000u64);
    oracle.verify_and_score(asset.clone(), accurate);

    println!("OK scored asset={} accurate={}", asset, accurate);
    println!("reputation={}", oracle.get_reputation(asset));
}
