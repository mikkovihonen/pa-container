use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{BufRead, Write};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolDefinition {
    pub name: String,
    pub description: String,
    #[serde(rename = "inputSchema")]
    pub input_schema: Value,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RpcRequest {
    pub jsonrpc: Option<String>,
    pub id: Option<Value>,
    pub method: String,
    pub params: Option<Value>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RpcResponse {
    pub jsonrpc: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<Value>,
}

pub type ToolHandler = dyn Fn(&str, &Value) -> Result<Value> + Send + Sync;

pub fn handle_rpc_request(
    server_name: &str,
    server_version: &str,
    tools: &[ToolDefinition],
    handler: &ToolHandler,
    req: &RpcRequest,
) -> Option<RpcResponse> {
    match req.method.as_str() {
        "initialize" => Some(RpcResponse {
            jsonrpc: "2.0",
            id: req.id.clone(),
            result: Some(json!({
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": server_name,
                    "version": server_version
                }
            })),
            error: None,
        }),
        "notifications/initialized" => None,
        "ping" => Some(RpcResponse {
            jsonrpc: "2.0",
            id: req.id.clone(),
            result: Some(json!({})),
            error: None,
        }),
        "tools/list" => Some(RpcResponse {
            jsonrpc: "2.0",
            id: req.id.clone(),
            result: Some(json!({
                "tools": tools
            })),
            error: None,
        }),
        "tools/call" => {
            let params = req.params.as_ref().unwrap_or(&Value::Null);
            let tool_name = params.get("name").and_then(|v| v.as_str()).unwrap_or("");
            let arguments = params.get("arguments").cloned().unwrap_or(json!({}));

            match handler(tool_name, &arguments) {
                Ok(res) => {
                    let text = if res.is_string() {
                        res.as_str().unwrap().to_string()
                    } else {
                        serde_json::to_string_pretty(&res).unwrap_or_default()
                    };
                    Some(RpcResponse {
                        jsonrpc: "2.0",
                        id: req.id.clone(),
                        result: Some(json!({
                            "content": [
                                {
                                    "type": "text",
                                    "text": text
                                }
                            ]
                        })),
                        error: None,
                    })
                }
                Err(err) => Some(RpcResponse {
                    jsonrpc: "2.0",
                    id: req.id.clone(),
                    result: Some(json!({
                        "content": [
                            {
                                "type": "text",
                                "text": format!("Error: {err:#}")
                            }
                        ],
                        "isError": true
                    })),
                    error: None,
                }),
            }
        }
        _ => Some(RpcResponse {
            jsonrpc: "2.0",
            id: req.id.clone(),
            result: None,
            error: Some(json!({
                "code": -32601,
                "message": format!("Method not found: {}", req.method)
            })),
        }),
    }
}

pub fn run_stdio_server(
    server_name: &str,
    server_version: &str,
    tools: Vec<ToolDefinition>,
    handler: Box<ToolHandler>,
) -> Result<()> {
    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        if let Ok(req) = serde_json::from_str::<RpcRequest>(trimmed) {
            if let Some(resp) =
                handle_rpc_request(server_name, server_version, &tools, &*handler, &req)
            {
                let serialized = serde_json::to_string(&resp)?;
                writeln!(stdout, "{serialized}")?;
                stdout.flush()?;
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_mcp_initialize_and_tools_call() {
        let tools = vec![ToolDefinition {
            name: "test_echo".to_string(),
            description: "Echo argument".to_string(),
            input_schema: json!({ "type": "object" }),
        }];

        let handler = Box::new(|name: &str, args: &Value| {
            if name == "test_echo" {
                Ok(json!({ "echo": args }))
            } else {
                anyhow::bail!("Unknown tool")
            }
        });

        let init_req = RpcRequest {
            jsonrpc: Some("2.0".to_string()),
            id: Some(json!(1)),
            method: "initialize".to_string(),
            params: None,
        };
        let init_resp = handle_rpc_request("test_server", "1.0.0", &tools, &*handler, &init_req)
            .expect("Response expected");
        assert_eq!(init_resp.id, Some(json!(1)));
        assert!(init_resp.result.is_some());

        let call_req = RpcRequest {
            jsonrpc: Some("2.0".to_string()),
            id: Some(json!(2)),
            method: "tools/call".to_string(),
            params: Some(json!({
                "name": "test_echo",
                "arguments": { "msg": "hello" }
            })),
        };
        let call_resp = handle_rpc_request("test_server", "1.0.0", &tools, &*handler, &call_req)
            .expect("Response expected");
        assert_eq!(call_resp.id, Some(json!(2)));
        let result = call_resp.result.unwrap();
        assert!(result.get("content").is_some());
    }
}
