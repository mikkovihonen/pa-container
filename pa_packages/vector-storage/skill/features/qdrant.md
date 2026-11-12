## Optional Feature: Qdrant Vector Database Server (`qdrant`)

High-performance vector similarity search engine and vector database daemon.

### Usage
- Start local daemon: `qdrant --config-path /path/to/config.yaml`
- Default REST API: `http://localhost:6333`
- Default gRPC API: `http://localhost:6334`
- Health check: `curl -s http://localhost:6333/readyz`
