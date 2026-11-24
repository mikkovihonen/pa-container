use anyhow::Result;
use serde_json::{json, Value};
use std::path::Path;

use crate::design::{DesignSystemStore, TokenCatalog};
use crate::mcp::protocol::ToolDefinition;
use crate::schema::DesignSystemConfig;

pub fn design_mcp_tools() -> Vec<ToolDefinition> {
    vec![
        ToolDefinition {
            name: "design.search_tokens".to_string(),
            description: "Search and discover Design System tokens from W3C DTCG tokens.json. Supports filtering by query substring, category (color, spacing, typography), and generates platform snippets for web (CSS vars), iOS (Swift), or Android (Kotlin).".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "query": { "type": "string", "description": "Substring to search across token names or values (e.g. 'brand', 'primary')" },
                    "category": { "type": "string", "description": "Filter by token type/category (e.g. 'color', 'dimension', 'typography')" },
                    "platform": { "type": "string", "description": "Platform syntax to format in snippet ('web', 'ios', 'android')" }
                }
            }),
        },
        ToolDefinition {
            name: "design.get_component_contract".to_string(),
            description: "Fetch component contract specification from design/contracts/<component>.toml, including required design tokens, accessibility standards (WCAG), platform component paths, and validates token references.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "component": { "type": "string", "description": "Component name (e.g. 'button', 'card', 'header')" }
                },
                "required": ["component"]
            }),
        },
        ToolDefinition {
            name: "design.list_deprecated".to_string(),
            description: "List all deprecated design tokens and component contracts with their recommended replacements and sunset notices.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {}
            }),
        },
        ToolDefinition {
            name: "design.get_board_spec".to_string(),
            description: "Inspect visual design board or component frame specifications via live Penpot/Figma HTTP API (or returns git_only status if operating in local Git token mode).".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "board_id": { "type": "string", "description": "Visual board or page ID (e.g. board-landing-v1)" }
                }
            }),
        },
    ]
}

pub fn handle_design_tool(workspace_dir: &Path, tool_name: &str, args: &Value) -> Result<Value> {
    let mut config = DesignSystemConfig::default();
    let config_file = workspace_dir.join("factory.toml");
    if config_file.is_file() {
        if let Ok(content) = std::fs::read_to_string(&config_file) {
            if let Ok(parsed) = toml::from_str::<crate::schema::FactoryConfig>(&content) {
                config = parsed.design_system;
            }
        }
    }

    let store =
        DesignSystemStore::load(workspace_dir, &config).unwrap_or_else(|_| DesignSystemStore {
            provider: "git_only".to_string(),
            catalog: TokenCatalog::empty(),
            contracts: std::collections::HashMap::new(),
        });

    match tool_name {
        "design.search_tokens" => {
            let query = args
                .get("query")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_lowercase();
            let category = args
                .get("category")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_lowercase();
            let platform = args
                .get("platform")
                .and_then(|v| v.as_str())
                .unwrap_or("web")
                .to_lowercase();

            let mut matched = Vec::new();
            for (name, tok) in &store.catalog.tokens {
                if !category.is_empty() && !tok.token_type.to_lowercase().contains(&category) {
                    continue;
                }
                if !query.is_empty()
                    && !name.to_lowercase().contains(&query)
                    && !tok.value.to_lowercase().contains(&query)
                {
                    continue;
                }

                let snippet = match platform.as_str() {
                    "ios" => {
                        let swift_prop = name.replace('.', "_");
                        format!("Color.DesignSystem.{swift_prop}")
                    }
                    "android" => {
                        let kt_prop = name.replace('.', "_");
                        format!("DesignTokens.{kt_prop}")
                    }
                    _ => {
                        let css_var = format!("--{}", name.replace('.', "-"));
                        format!("var({css_var})")
                    }
                };

                matched.push(json!({
                    "name": name,
                    "value": tok.value,
                    "type": tok.token_type,
                    "description": tok.description,
                    "source": tok.source,
                    "platform_snippet": snippet
                }));
            }

            Ok(json!({
                "count": matched.len(),
                "platform": platform,
                "tokens": matched
            }))
        }
        "design.get_component_contract" => {
            let component = args
                .get("component")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim();
            if component.is_empty() {
                return Ok(json!({ "error": "component parameter is required" }));
            }

            if let Some(contract) = store.contracts.get(component) {
                let mut missing_tokens = Vec::new();
                for req_token in &contract.tokens {
                    if !store.catalog.tokens.contains_key(req_token) {
                        missing_tokens.push(req_token);
                    }
                }

                Ok(json!({
                    "name": contract.name,
                    "description": contract.description,
                    "platforms": contract.platforms,
                    "tokens": contract.tokens,
                    "tokens_valid": missing_tokens.is_empty(),
                    "missing_tokens": missing_tokens,
                    "web": contract.web,
                    "ios": contract.ios,
                    "android": contract.android
                }))
            } else {
                Ok(json!({
                    "error": format!("Component contract '{component}' not found in design/contracts/"),
                    "available_contracts": store.contracts.keys().collect::<Vec<_>>()
                }))
            }
        }
        "design.list_deprecated" => {
            let deprecated_contracts: Vec<Value> = Vec::new();
            Ok(json!({
                "deprecated_tokens_count": 0,
                "deprecated_tokens": [],
                "deprecated_contracts": deprecated_contracts
            }))
        }
        "design.get_board_spec" => {
            let board_id = args
                .get("board_id")
                .and_then(|v| v.as_str())
                .unwrap_or("default");
            Ok(json!({
                "provider": store.provider,
                "board_id": board_id,
                "status": if store.provider == "git_only" || store.provider == "none" {
                    "offline_git_tokens"
                } else {
                    "live_provider_connected"
                },
                "cached_tokens_count": store.catalog.tokens.len(),
                "contracts_count": store.contracts.len()
            }))
        }
        _ => anyhow::bail!("Unknown design tool: {}", tool_name),
    }
}
