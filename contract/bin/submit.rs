//! 向【已部署】的 RwaOracle 合约提交一条数据（供 Python Agent 通过 subprocess 调用）。
//!
//! 参数通过环境变量传入：
//!   ORACLE_CONTRACT_HASH = hash-...（已部署合约的 package hash）
//!   SUBMIT_ASSET         = 资产标识，如 XAU/USD
//!   SUBMIT_VALUE         = 价格（放大 1e6 后的整数）
//!   SUBMIT_CONFIDENCE    = 置信度 0-100
//!
//! 运行：cargo run --bin submit --features livenet

use std::env;
use std::str::FromStr;

use contract::rwa_oracle::RwaOracle;
use odra::casper_types::U256;
use odra::host::HostRefLoader;
use odra::prelude::Address;

fn main() {
    let livenet = odra_casper_livenet_env::env();

    let contract_hash = env::var("ORACLE_CONTRACT_HASH").expect("缺少 ORACLE_CONTRACT_HASH");
    let address = Address::from_str(&contract_hash).expect("合约地址格式错误");
    let asset = env::var("SUBMIT_ASSET").expect("缺少 SUBMIT_ASSET");
    let value: u64 = env::var("SUBMIT_VALUE")
        .expect("缺少 SUBMIT_VALUE")
        .parse()
        .expect("SUBMIT_VALUE 必须是整数");
    let confidence: u8 = env::var("SUBMIT_CONFIDENCE")
        .expect("缺少 SUBMIT_CONFIDENCE")
        .parse()
        .expect("SUBMIT_CONFIDENCE 必须是 0-100 的整数");

    let mut oracle = RwaOracle::load(&livenet, address);
    livenet.set_gas(10_000_000_000u64);
    oracle.submit_data(asset.clone(), U256::from(value), confidence);

    println!("OK asset={} value={} confidence={}", asset, value, confidence);
    println!("submission_count={}", oracle.get_submission_count());
    println!("reputation={}", oracle.get_reputation());
}
