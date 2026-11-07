// Pre-seed T3 Code settings for active agent driver.
const fs = require("node:fs");
const path = "/home/agent/.t3/userdata/settings.json";

try {
    fs.mkdirSync(require("node:path").dirname(path), { recursive: true });
    let settings = {};
    try {
        settings = JSON.parse(fs.readFileSync(path, "utf8"));
    } catch {}
    const enabledList = (process.env.PA_CONTAINER_ENABLED_AGENTS || process.env.PA_CONTAINER_AGENT || "pi")
        .toLowerCase()
        .split(",")
        .map((s) => s.trim());
    const activeAgent = (process.env.PA_CONTAINER_AGENT || enabledList[0] || "pi").toLowerCase();

    const isClaudeEnabled = enabledList.some((a) => a === "claude" || a === "claude-code");
    const isCodexEnabled = enabledList.some((a) => a === "codex" || a === "opencode" || a === "open-code");
    const isPiEnabled = enabledList.some((a) => a === "pi" || a === "default");

    const isClaudeActive = activeAgent === "claude" || activeAgent === "claude-code";
    const isCodexActive = activeAgent === "codex" || activeAgent === "opencode" || activeAgent === "open-code";
    const isPiActive = !isClaudeActive && !isCodexActive;

    settings.providerInstances = settings.providerInstances || {};
    settings.providerInstances.pi = Object.assign(settings.providerInstances.pi || {}, {
        driver: "pi",
        enabled: isPiEnabled,
    });
    settings.providerInstances.codex = Object.assign(settings.providerInstances.codex || {}, {
        driver: "codex",
        enabled: isCodexEnabled,
    });
    settings.providerInstances.claudeAgent = Object.assign(settings.providerInstances.claudeAgent || {}, {
        driver: "claudeAgent",
        enabled: isClaudeEnabled,
    });

    const activeInstanceId = isClaudeActive ? "claudeAgent" : isCodexActive ? "codex" : "pi";
    if (
        !settings.textGenerationModelSelection ||
        !settings.textGenerationModelSelection.instanceId ||
        settings.textGenerationModelSelection.instanceId === "codex" ||
        settings.textGenerationModelSelection.instanceId === "pi" ||
        settings.textGenerationModelSelection.instanceId === "claudeAgent"
    ) {
        settings.textGenerationModelSelection = { instanceId: activeInstanceId, model: "default" };
    }
    fs.writeFileSync(path, JSON.stringify(settings, null, 2));
} catch (err) {
    console.error("Warning: failed to seed T3 settings:", err.message);
}
