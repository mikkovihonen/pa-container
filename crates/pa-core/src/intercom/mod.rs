use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};

use crate::mcp::protocol::ToolDefinition;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PeerRecord {
    pub name: String,
    pub worktree: String,
    pub registered_at: String,
    pub last_seen: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IntercomMessage {
    pub id: String,
    pub from: String,
    pub to: String,
    pub message: String,
    pub timestamp: String,
    pub acknowledged: bool,
}

pub fn get_intercom_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("PA_INTERCOM_DIR") {
        PathBuf::from(dir)
    } else {
        PathBuf::from("/tmp/pa-intercom")
    }
}

pub fn register_peer(dir: &Path, name: &str, worktree: &str) -> Result<PeerRecord> {
    let peers_dir = dir.join("peers");
    fs::create_dir_all(&peers_dir)?;

    let now = chrono_now_iso();
    let record = PeerRecord {
        name: name.to_string(),
        worktree: worktree.to_string(),
        registered_at: now.clone(),
        last_seen: now,
    };

    let peer_file = peers_dir.join(format!("{name}.json"));
    let serialized = serde_json::to_string_pretty(&record)?;
    fs::write(&peer_file, serialized)?;
    Ok(record)
}

pub fn list_peers(dir: &Path) -> Result<Vec<PeerRecord>> {
    let peers_dir = dir.join("peers");
    if !peers_dir.is_dir() {
        return Ok(Vec::new());
    }

    let mut peers = Vec::new();
    for entry in fs::read_dir(peers_dir)?.flatten() {
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) == Some("json") {
            if let Ok(content) = fs::read_to_string(&path) {
                if let Ok(p) = serde_json::from_str::<PeerRecord>(&content) {
                    peers.push(p);
                }
            }
        }
    }
    peers.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(peers)
}

pub fn send_message(dir: &Path, from: &str, to: &str, body: &str) -> Result<IntercomMessage> {
    let id = format!("{:016x}", rand::random::<u64>());
    let now = chrono_now_iso();
    let msg = IntercomMessage {
        id: id.clone(),
        from: from.to_string(),
        to: to.to_string(),
        message: body.to_string(),
        timestamp: now,
        acknowledged: false,
    };

    let serialized = serde_json::to_string_pretty(&msg)?;

    let targets = if to == "all" || to == "*" {
        list_peers(dir)?
            .into_iter()
            .map(|p| p.name)
            .filter(|n| n != from)
            .collect::<Vec<_>>()
    } else {
        vec![to.to_string()]
    };

    for target in targets {
        let inbox_dir = dir.join("inbox").join(&target);
        fs::create_dir_all(&inbox_dir)?;
        let msg_file = inbox_dir.join(format!("{id}.json"));
        fs::write(&msg_file, &serialized)?;
    }

    Ok(msg)
}

pub fn read_inbox(dir: &Path, peer: &str, unread_only: bool) -> Result<Vec<IntercomMessage>> {
    let inbox_dir = dir.join("inbox").join(peer);
    if !inbox_dir.is_dir() {
        return Ok(Vec::new());
    }

    let mut messages = Vec::new();
    for entry in fs::read_dir(&inbox_dir)?.flatten() {
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) == Some("json") {
            if let Ok(content) = fs::read_to_string(&path) {
                if let Ok(msg) = serde_json::from_str::<IntercomMessage>(&content) {
                    if !unread_only || !msg.acknowledged {
                        messages.push(msg);
                    }
                }
            }
        }
    }
    messages.sort_by(|a, b| a.timestamp.cmp(&b.timestamp));
    Ok(messages)
}

pub fn ack_message(dir: &Path, peer: &str, msg_id: &str) -> Result<bool> {
    let inbox_dir = dir.join("inbox").join(peer);
    let msg_file = inbox_dir.join(format!("{msg_id}.json"));
    if msg_file.is_file() {
        let content = fs::read_to_string(&msg_file)?;
        let mut msg: IntercomMessage = serde_json::from_str(&content)?;
        msg.acknowledged = true;
        fs::write(&msg_file, serde_json::to_string_pretty(&msg)?)?;
        Ok(true)
    } else {
        Ok(false)
    }
}

pub fn intercom_mcp_tools() -> Vec<ToolDefinition> {
    vec![
        ToolDefinition {
            name: "intercom_peers".to_string(),
            description: "List active human and coding agent peers registered on AgentIntercom across worktrees.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {}
            }),
        },
        ToolDefinition {
            name: "intercom_send".to_string(),
            description: "Send a structured message, API contract update, or delegated task to another peer on AgentIntercom.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "to": { "type": "string", "description": "Recipient peer name (or 'all' for broadcast)" },
                    "message": { "type": "string", "description": "Message body" }
                },
                "required": ["to", "message"]
            }),
        },
        ToolDefinition {
            name: "intercom_inbox".to_string(),
            description: "Read incoming messages in the current agent's durable AgentIntercom inbox.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "unread_only": { "type": "boolean", "description": "Filter for unacknowledged messages only (default: true)" }
                }
            }),
        },
        ToolDefinition {
            name: "intercom_ack".to_string(),
            description: "Acknowledge a message ID in the AgentIntercom inbox after acting on it.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "id": { "type": "string", "description": "Message ID to acknowledge" }
                },
                "required": ["id"]
            }),
        },
    ]
}

pub fn handle_intercom_tool(tool_name: &str, args: &Value) -> Result<Value> {
    let dir = get_intercom_dir();
    let current_peer = std::env::var("AGENTINTERCOM_PEER")
        .or_else(|_| std::env::var("PA_INTERCOM_PEER"))
        .unwrap_or_else(|_| "agent".to_string());

    match tool_name {
        "intercom_peers" => {
            let peers = list_peers(&dir)?;
            Ok(json!({ "peers": peers }))
        }
        "intercom_send" => {
            let to = args
                .get("to")
                .and_then(|v| v.as_str())
                .context("to is required")?;
            let body = args
                .get("message")
                .and_then(|v| v.as_str())
                .context("message is required")?;
            let msg = send_message(&dir, &current_peer, to, body)?;
            Ok(json!({ "status": "sent", "message": msg }))
        }
        "intercom_inbox" => {
            let unread = args
                .get("unread_only")
                .and_then(|v| v.as_bool())
                .unwrap_or(true);
            let msgs = read_inbox(&dir, &current_peer, unread)?;
            Ok(json!({ "messages": msgs }))
        }
        "intercom_ack" => {
            let id = args
                .get("id")
                .and_then(|v| v.as_str())
                .context("id is required")?;
            let acked = ack_message(&dir, &current_peer, id)?;
            Ok(json!({ "id": id, "acknowledged": acked }))
        }
        _ => anyhow::bail!("Unknown intercom tool: {}", tool_name),
    }
}

fn chrono_now_iso() -> String {
    let now = std::time::SystemTime::now();
    let duration = now
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    format!("{}.{:03}Z", duration.as_secs(), duration.subsec_millis())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_intercom_lifecycle() {
        let td = tempdir().unwrap();
        let dir = td.path();

        let peer_a = register_peer(dir, "agent-a", "/workspace/a").unwrap();
        let peer_b = register_peer(dir, "agent-b", "/workspace/b").unwrap();
        assert_eq!(peer_a.name, "agent-a");
        assert_eq!(peer_b.name, "agent-b");

        let peers = list_peers(dir).unwrap();
        assert_eq!(peers.len(), 2);

        let msg = send_message(dir, "agent-a", "agent-b", "Hello agent B!").unwrap();
        assert_eq!(msg.from, "agent-a");
        assert_eq!(msg.to, "agent-b");

        let inbox_b = read_inbox(dir, "agent-b", true).unwrap();
        assert_eq!(inbox_b.len(), 1);
        assert_eq!(inbox_b[0].message, "Hello agent B!");

        let acked = ack_message(dir, "agent-b", &msg.id).unwrap();
        assert!(acked);

        let unread = read_inbox(dir, "agent-b", true).unwrap();
        assert!(unread.is_empty());
    }
}
