#![doc = "从 odra 合约生成 schema 定义的二进制入口。"]
#[allow(unused_imports, clippy::single_component_path_imports)]
use contract;

#[cfg(not(target_arch = "wasm32"))]
extern "Rust" {
    fn module_schema() -> odra::contract_def::ContractBlueprint;
    fn casper_contract_schema() -> odra::schema::casper_contract_schema::ContractSchema;
}

#[cfg(not(target_arch = "wasm32"))]
fn main() {
    odra_build::schema(unsafe { crate::module_schema() }, unsafe {
        crate::casper_contract_schema()
    });
}
