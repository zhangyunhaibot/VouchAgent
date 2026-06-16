//! RWA 链上预言机合约。
//!
//! 由授权的 AI Agent 提交真实世界资产（黄金、汇率、美股等）的价格数据，
//! 合约存储每个资产的最新数据点，并为该 Agent 维护一个「信誉分」：
//! 历史数据被验证越准确，信誉分越高，从而形成一个去信任化的 RWA 预言机。

use odra::casper_types::U256;
use odra::prelude::*;

/// 单个资产的数据点。
#[odra::odra_type]
pub struct DataPoint {
    /// 资产价格（按 1e6 放大后的整数，避免使用浮点数）。
    pub value: U256,
    /// 提交时的区块时间戳（毫秒）。
    pub timestamp: u64,
    /// LLM 对该数据可信度的判断，取值 0-100。
    pub confidence: u8,
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
}

/// 数据提交事件。
#[odra::event]
pub struct DataSubmitted {
    /// 资产标识，如 "XAU/USD"。
    pub asset: String,
    /// 价格（放大后）。
    pub value: U256,
    /// 置信度。
    pub confidence: u8,
    /// 时间戳。
    pub timestamp: u64,
}

/// 信誉分更新事件。
#[odra::event]
pub struct ReputationUpdated {
    /// 更新后的信誉分。
    pub new_score: U256,
    /// 本次核对是否判定为准确。
    pub accurate: bool,
}

/// RWA 预言机模块。
#[odra::module(
    events = [DataSubmitted, ReputationUpdated],
    errors = Error
)]
pub struct RwaOracle {
    /// 合约部署者（管理员）。
    owner: Var<Address>,
    /// 授权提交数据的 AI Agent 地址。
    oracle_agent: Var<Address>,
    /// 资产标识 -> 最新数据点。
    data_points: Mapping<String, DataPoint>,
    /// Agent 信誉分（初始 100）。
    reputation: Var<U256>,
    /// 累计提交次数。
    submission_count: Var<u64>,
}

#[odra::module]
impl RwaOracle {
    /// 初始化：调用者成为 owner，并指定授权的预言机 Agent。
    pub fn init(&mut self, oracle_agent: Address) {
        self.owner.set(self.env().caller());
        self.oracle_agent.set(oracle_agent);
        self.reputation.set(U256::from(100u32));
        self.submission_count.set(0u64);
    }

    /// 提交一条资产数据。仅授权 Agent 可调用；每次调用都会产生一笔链上交易。
    pub fn submit_data(&mut self, asset: String, value: U256, confidence: u8) {
        self.assert_oracle();
        if confidence > 100 {
            self.env().revert(Error::InvalidConfidence);
        }
        let timestamp = self.env().get_block_time();
        self.data_points
            .set(&asset, DataPoint { value, timestamp, confidence });
        self.submission_count
            .set(self.submission_count.get_or_default() + 1);
        self.env().emit_event(DataSubmitted {
            asset,
            value,
            confidence,
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

    /// 读取当前信誉分。
    pub fn get_reputation(&self) -> U256 {
        self.reputation.get_or_default()
    }

    /// 读取累计提交次数。
    pub fn get_submission_count(&self) -> u64 {
        self.submission_count.get_or_default()
    }

    /// 读取授权的预言机 Agent 地址。
    pub fn get_oracle_agent(&self) -> Address {
        self.oracle_agent.get_or_revert_with(Error::NotOracle)
    }

    /// 事后核对历史数据准确性并更新信誉分。仅 owner 可调用。
    /// 准确则 +1，不准确则 -1（不低于 0）。
    pub fn verify_and_score(&mut self, accurate: bool) {
        self.assert_owner();
        let current = self.reputation.get_or_default();
        let new_score = if accurate {
            current + U256::from(1u32)
        } else if current.is_zero() {
            U256::zero()
        } else {
            current - U256::from(1u32)
        };
        self.reputation.set(new_score);
        self.env().emit_event(ReputationUpdated { new_score, accurate });
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
        assert_eq!(contract.get_reputation(), U256::from(100u32));
        assert_eq!(contract.get_submission_count(), 0u64);
        assert_eq!(contract.get_oracle_agent(), env.get_account(1));
    }

    #[test]
    fn oracle_can_submit_data() {
        let (env, mut contract) = setup();
        // 切换调用者为授权 Agent。
        env.set_caller(env.get_account(1));
        contract.submit_data(String::from("XAU/USD"), U256::from(2_345_000_000u64), 95);

        let dp = contract.get_data(String::from("XAU/USD"));
        assert_eq!(dp.value, U256::from(2_345_000_000u64));
        assert_eq!(dp.confidence, 95);
        assert_eq!(contract.get_submission_count(), 1u64);
    }

    #[test]
    fn non_oracle_cannot_submit() {
        let (env, mut contract) = setup();
        // account(2) 不是授权 Agent。
        env.set_caller(env.get_account(2));
        let result = contract.try_submit_data(String::from("XAU/USD"), U256::from(1u64), 90);
        assert_eq!(result, Err(Error::NotOracle.into()));
    }

    #[test]
    fn confidence_must_be_valid() {
        let (env, mut contract) = setup();
        env.set_caller(env.get_account(1));
        let result = contract.try_submit_data(String::from("XAU/USD"), U256::from(1u64), 101);
        assert_eq!(result, Err(Error::InvalidConfidence.into()));
    }

    #[test]
    fn owner_can_score_reputation() {
        let (_env, mut contract) = setup();
        // 默认调用者为 account(0)，即 owner。
        contract.verify_and_score(true);
        assert_eq!(contract.get_reputation(), U256::from(101u32));
        contract.verify_and_score(false);
        assert_eq!(contract.get_reputation(), U256::from(100u32));
    }

    #[test]
    fn non_owner_cannot_score() {
        let (env, mut contract) = setup();
        env.set_caller(env.get_account(1));
        let result = contract.try_verify_and_score(true);
        assert_eq!(result, Err(Error::NotOwner.into()));
    }
}
