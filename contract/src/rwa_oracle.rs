//! RWA 链上预言机合约 v2。
//!
//! 由授权的 AI Agent 提交多种真实世界资产（黄金、汇率、美股等）的数据。
//! v2 相比 v1 的增强：
//! - 资产注册表：可在链上枚举所有已上报的资产（供 Dashboard 展示）；
//! - per-资产信誉分：每个数据源各有独立的信誉分，随历史准确度增减；
//! - DataPoint 增加 source_count：记录有几个独立数据源参与了交叉验证。

use odra::casper_types::U256;
use odra::prelude::*;

/// 新资产的初始信誉分。
const INITIAL_REPUTATION: u32 = 100;

/// 单个资产的数据点。
#[odra::odra_type]
pub struct DataPoint {
    /// 资产价格（按 1e6 放大后的整数，避免使用浮点数）。
    pub value: U256,
    /// 提交时的区块时间戳（毫秒）。
    pub timestamp: u64,
    /// LLM 对该数据可信度的判断，取值 0-100。
    pub confidence: u8,
    /// 参与本次交叉验证的独立数据源数量。
    pub source_count: u8,
}

/// 合约错误码。
#[odra::odra_error]
pub enum Error {
    /// 调用者不是授权的预言机 Agent。
    NotOracle = 1,
    /// 调用者不是合约 owner。
    NotOwner = 2,
    /// 查询的资产数据不存在。
    DataNotFound = 3,
    /// 置信度超出 0-100 范围。
    InvalidConfidence = 4,
    /// 资产索引越界。
    IndexOutOfRange = 5,
}

/// 数据提交事件。
#[odra::event]
pub struct DataSubmitted {
    pub asset: String,
    pub value: U256,
    pub confidence: u8,
    pub source_count: u8,
    pub timestamp: u64,
}

/// 信誉分更新事件。
#[odra::event]
pub struct ReputationUpdated {
    pub asset: String,
    pub new_score: U256,
    pub accurate: bool,
}

/// 新资产注册事件。
#[odra::event]
pub struct AssetRegistered {
    pub asset: String,
}

/// RWA 预言机模块 v2。
#[odra::module(
    events = [DataSubmitted, ReputationUpdated, AssetRegistered],
    errors = Error
)]
pub struct RwaOracle {
    /// 合约部署者（管理员）。
    owner: Var<Address>,
    /// 授权提交数据的 AI Agent 地址。
    oracle_agent: Var<Address>,
    /// 资产标识 -> 最新数据点。
    data_points: Mapping<String, DataPoint>,
    /// 资产标识 -> 信誉分（初始 100）。
    asset_reputation: Mapping<String, U256>,
    /// 资产标识 -> 累计提交次数。
    asset_submissions: Mapping<String, u64>,
    /// 资产标识 -> 是否已注册（用于去重）。
    is_registered: Mapping<String, bool>,
    /// 索引 -> 资产标识（用于枚举注册表）。
    asset_at: Mapping<u32, String>,
    /// 已注册资产数量。
    asset_count: Var<u32>,
    /// 全局累计提交次数。
    total_submissions: Var<u64>,
}

#[odra::module]
impl RwaOracle {
    /// 初始化：调用者成为 owner，并指定授权的预言机 Agent。
    pub fn init(&mut self, oracle_agent: Address) {
        self.owner.set(self.env().caller());
        self.oracle_agent.set(oracle_agent);
        self.asset_count.set(0u32);
        self.total_submissions.set(0u64);
    }

    /// 提交一条资产数据。仅授权 Agent 可调用；每次调用产生一笔链上交易。
    /// 新资产首次出现时自动注册并初始化信誉分。
    pub fn submit_data(&mut self, asset: String, value: U256, confidence: u8, source_count: u8) {
        self.assert_oracle();
        if confidence > 100 {
            self.env().revert(Error::InvalidConfidence);
        }

        // 新资产 → 注册进枚举表 + 初始化信誉分。
        if !self.is_registered.get(&asset).unwrap_or(false) {
            let idx = self.asset_count.get_or_default();
            self.asset_at.set(&idx, asset.clone());
            self.asset_count.set(idx + 1);
            self.is_registered.set(&asset, true);
            self.asset_reputation
                .set(&asset, U256::from(INITIAL_REPUTATION));
            self.env().emit_event(AssetRegistered {
                asset: asset.clone(),
            });
        }

        let timestamp = self.env().get_block_time();
        self.data_points.set(
            &asset,
            DataPoint {
                value,
                timestamp,
                confidence,
                source_count,
            },
        );
        let count = self.asset_submissions.get(&asset).unwrap_or(0) + 1;
        self.asset_submissions.set(&asset, count);
        self.total_submissions
            .set(self.total_submissions.get_or_default() + 1);

        self.env().emit_event(DataSubmitted {
            asset,
            value,
            confidence,
            source_count,
            timestamp,
        });
    }

    /// 读取某资产的最新数据点；不存在则 revert。
    pub fn get_data(&self, asset: String) -> DataPoint {
        match self.data_points.get(&asset) {
            Some(dp) => dp,
            None => self.env().revert(Error::DataNotFound),
        }
    }

    /// 读取某资产的信誉分。
    pub fn get_reputation(&self, asset: String) -> U256 {
        self.asset_reputation.get(&asset).unwrap_or_default()
    }

    /// 读取某资产的累计提交次数。
    pub fn get_asset_submissions(&self, asset: String) -> u64 {
        self.asset_submissions.get(&asset).unwrap_or_default()
    }

    /// 读取全局累计提交次数。
    pub fn get_total_submissions(&self) -> u64 {
        self.total_submissions.get_or_default()
    }

    /// 读取已注册资产数量（配合 get_asset_at 枚举）。
    pub fn get_asset_count(&self) -> u32 {
        self.asset_count.get_or_default()
    }

    /// 按索引读取已注册的资产标识。
    pub fn get_asset_at(&self, index: u32) -> String {
        match self.asset_at.get(&index) {
            Some(a) => a,
            None => self.env().revert(Error::IndexOutOfRange),
        }
    }

    /// 读取授权的预言机 Agent 地址。
    pub fn get_oracle_agent(&self) -> Address {
        self.oracle_agent.get_or_revert_with(Error::NotOracle)
    }

    /// 事后核对某资产历史数据准确性并更新其信誉分。仅 owner 可调用。
    pub fn verify_and_score(&mut self, asset: String, accurate: bool) {
        self.assert_owner();
        let current = self.asset_reputation.get(&asset).unwrap_or_default();
        let new_score = if accurate {
            current + U256::from(1u32)
        } else if current.is_zero() {
            U256::zero()
        } else {
            current - U256::from(1u32)
        };
        self.asset_reputation.set(&asset, new_score);
        self.env().emit_event(ReputationUpdated {
            asset,
            new_score,
            accurate,
        });
    }

    /// 更换授权的预言机 Agent。仅 owner 可调用。
    pub fn set_oracle_agent(&mut self, new_agent: Address) {
        self.assert_owner();
        self.oracle_agent.set(new_agent);
    }

    /// 断言调用者是授权的预言机 Agent。
    fn assert_oracle(&self) {
        let agent = self.oracle_agent.get_or_revert_with(Error::NotOracle);
        if self.env().caller() != agent {
            self.env().revert(Error::NotOracle);
        }
    }

    /// 断言调用者是 owner。
    fn assert_owner(&self) {
        let owner = self.owner.get_or_revert_with(Error::NotOwner);
        if self.env().caller() != owner {
            self.env().revert(Error::NotOwner);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use odra::host::{Deployer, HostRef};

    /// 部署合约：account(0) 为 owner，account(1) 为授权 Agent。
    fn setup() -> (odra::host::HostEnv, RwaOracleHostRef) {
        let env = odra_test::env();
        let agent = env.get_account(1);
        let contract = RwaOracle::deploy(&env, RwaOracleInitArgs { oracle_agent: agent });
        (env, contract)
    }

    #[test]
    fn init_state_is_correct() {
        let (env, contract) = setup();
        assert_eq!(contract.get_total_submissions(), 0u64);
        assert_eq!(contract.get_asset_count(), 0u32);
        assert_eq!(contract.get_oracle_agent(), env.get_account(1));
    }

    #[test]
    fn oracle_submits_and_registers_asset() {
        let (env, mut contract) = setup();
        env.set_caller(env.get_account(1));
        contract.submit_data(String::from("XAU/USD"), U256::from(4_330_000_000u64), 95, 2);

        let dp = contract.get_data(String::from("XAU/USD"));
        assert_eq!(dp.value, U256::from(4_330_000_000u64));
        assert_eq!(dp.confidence, 95);
        assert_eq!(dp.source_count, 2);
        assert_eq!(contract.get_asset_count(), 1u32);
        assert_eq!(contract.get_asset_at(0), String::from("XAU/USD"));
        assert_eq!(
            contract.get_reputation(String::from("XAU/USD")),
            U256::from(100u32)
        );
        assert_eq!(contract.get_asset_submissions(String::from("XAU/USD")), 1u64);
        assert_eq!(contract.get_total_submissions(), 1u64);
    }

    #[test]
    fn multiple_assets_tracked_separately() {
        let (env, mut contract) = setup();
        env.set_caller(env.get_account(1));
        contract.submit_data(String::from("XAU/USD"), U256::from(4_330_000_000u64), 95, 2);
        contract.submit_data(String::from("EUR/USD"), U256::from(1_080_000u64), 88, 2);
        contract.submit_data(String::from("XAU/USD"), U256::from(4_331_000_000u64), 96, 2);

        assert_eq!(contract.get_asset_count(), 2u32);
        assert_eq!(contract.get_asset_submissions(String::from("XAU/USD")), 2u64);
        assert_eq!(contract.get_asset_submissions(String::from("EUR/USD")), 1u64);
        assert_eq!(contract.get_total_submissions(), 3u64);
    }

    #[test]
    fn non_oracle_cannot_submit() {
        let (env, mut contract) = setup();
        env.set_caller(env.get_account(2));
        let result =
            contract.try_submit_data(String::from("XAU/USD"), U256::from(1u64), 90, 1);
        assert_eq!(result, Err(Error::NotOracle.into()));
    }

    #[test]
    fn confidence_must_be_valid() {
        let (env, mut contract) = setup();
        env.set_caller(env.get_account(1));
        let result =
            contract.try_submit_data(String::from("XAU/USD"), U256::from(1u64), 101, 1);
        assert_eq!(result, Err(Error::InvalidConfidence.into()));
    }

    #[test]
    fn owner_scores_per_asset_reputation() {
        let (env, mut contract) = setup();
        env.set_caller(env.get_account(1));
        contract.submit_data(String::from("XAU/USD"), U256::from(4_330_000_000u64), 95, 2);
        env.set_caller(env.get_account(0)); // owner
        contract.verify_and_score(String::from("XAU/USD"), true);
        assert_eq!(
            contract.get_reputation(String::from("XAU/USD")),
            U256::from(101u32)
        );
        contract.verify_and_score(String::from("XAU/USD"), false);
        assert_eq!(
            contract.get_reputation(String::from("XAU/USD")),
            U256::from(100u32)
        );
    }

    #[test]
    fn non_owner_cannot_score() {
        let (env, mut contract) = setup();
        env.set_caller(env.get_account(1));
        let result = contract.try_verify_and_score(String::from("XAU/USD"), true);
        assert_eq!(result, Err(Error::NotOwner.into()));
    }
}
