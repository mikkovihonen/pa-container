# AI & Agent Frameworks (`ai-frameworks`)

Provides high-level agentic architectures, stateful graph orchestration, type-safe agent schemas, and code-centric agent engines.

## Constituent Libraries
- `langgraph`: Build resilient, cyclic, stateful multi-agent workflows and human-in-the-loop applications.
- `pydantic-ai`: Production-ready, model-agnostic agent framework built around Pydantic v2 schemas and validation.
- `smolagents`: Lightweight library from Hugging Face where agents write Python actions and execute tools directly.

## Usage Guidelines
- **LangGraph State Graphs**:
    - Build stateful graphs:
        ```python
        from langgraph.graph import StateGraph, START, END
        from typing import TypedDict

        class AgentState(TypedDict):
            query: str
            result: str

        builder = StateGraph(AgentState)
        ```
- **PydanticAI Type-Safe Agents**:
    - Define agents with structured output models:
        ```python
        from pydantic_ai import Agent
        from pydantic import BaseModel

        class AnalysisOutput(BaseModel):
            summary: str
            confidence: float

        agent = Agent('openai:gpt-4o', result_type=AnalysisOutput)
        ```
- **smolagents Code Execution**:
    - Direct python execution agents:
        ```python
        from smolagents import CodeAgent, HfApiModel

        agent = CodeAgent(tools=[], model=HfApiModel())
        ```
