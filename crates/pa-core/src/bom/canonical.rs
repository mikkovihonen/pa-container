use anyhow::{Context, Result};
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

/// Serialize a serde serializable value to canonical RFC 8785 JSON bytes.
pub fn to_canonical_json_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    let json_val =
        serde_json::to_value(value).context("Failed to serialize to serde_json::Value")?;
    let mut out = Vec::new();
    canonicalize_value(&json_val, &mut out);
    Ok(out)
}

/// Serialize a serde serializable value to a canonical RFC 8785 JSON string.
pub fn to_canonical_json_string<T: Serialize>(value: &T) -> Result<String> {
    let bytes = to_canonical_json_bytes(value)?;
    String::from_utf8(bytes).context("Canonical JSON produced invalid UTF-8")
}

/// Computes the canonical SHA256 digest prefixed with "sha256:".
pub fn compute_canonical_sha256<T: Serialize>(value: &T) -> Result<String> {
    let canonical_bytes = to_canonical_json_bytes(value)?;
    let mut hasher = Sha256::new();
    hasher.update(&canonical_bytes);
    let digest = hasher.finalize();
    Ok(format!("sha256:{}", hex::encode(digest)))
}

fn canonicalize_value(val: &Value, out: &mut Vec<u8>) {
    match val {
        Value::Null => out.extend_from_slice(b"null"),
        Value::Bool(b) => {
            if *b {
                out.extend_from_slice(b"true");
            } else {
                out.extend_from_slice(b"false");
            }
        }
        Value::Number(num) => {
            // serde_json::Number to string is standard JSON number formatting
            out.extend_from_slice(num.to_string().as_bytes());
        }
        Value::String(s) => {
            let escaped = serde_json::to_string(s).unwrap_or_else(|_| format!("\"{}\"", s));
            out.extend_from_slice(escaped.as_bytes());
        }
        Value::Array(arr) => {
            out.push(b'[');
            for (i, elem) in arr.iter().enumerate() {
                if i > 0 {
                    out.push(b',');
                }
                canonicalize_value(elem, out);
            }
            out.push(b']');
        }
        Value::Object(map) => {
            out.push(b'{');
            // Sort keys lexicographically by UTF-16 code units (for ASCII / standard strings this matches UTF-8)
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort_by(|a, b| {
                let a_utf16: Vec<u16> = a.encode_utf16().collect();
                let b_utf16: Vec<u16> = b.encode_utf16().collect();
                a_utf16.cmp(&b_utf16)
            });

            for (i, key) in keys.iter().enumerate() {
                if i > 0 {
                    out.push(b',');
                }
                let escaped_key =
                    serde_json::to_string(key).unwrap_or_else(|_| format!("\"{}\"", key));
                out.extend_from_slice(escaped_key.as_bytes());
                out.push(b':');
                if let Some(val) = map.get(*key) {
                    canonicalize_value(val, out);
                }
            }
            out.push(b'}');
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_canonical_json_sorting() {
        let v1 = json!({
            "b": 2,
            "a": 1,
            "c": [3, 2, 1]
        });
        let v2 = json!({
            "a": 1,
            "c": [3, 2, 1],
            "b": 2
        });

        let s1 = to_canonical_json_string(&v1).unwrap();
        let s2 = to_canonical_json_string(&v2).unwrap();
        assert_eq!(s1, s2);
        assert_eq!(s1, r#"{"a":1,"b":2,"c":[3,2,1]}"#);

        let hash1 = compute_canonical_sha256(&v1).unwrap();
        let hash2 = compute_canonical_sha256(&v2).unwrap();
        assert_eq!(hash1, hash2);
        assert!(hash1.starts_with("sha256:"));
    }
}
