// Pre-seed T3 Code settings for active agent driver.
const fs = require("node:fs");
const path = "/home/agent/.pi/agent/t3/userdata/settings.json";

try {
    fs.mkdirSync(require("node:path").dirname(path), { recursive: true });
    let settings = {};
    try {
        settings = JSON.parse(fs.readFileSync(path, "utf8"));
    } catch {}
    const activeAgent = (process.env.PI_CONTAINER_AGENT || "pi").toLowerCase();
    const isClaude = activeAgent === "claude" || activeAgent === "claude-code";
    const isCodex = activeAgent === "codex";
    const isPi = !isClaude && !isCodex;

    settings.providerInstances = settings.providerInstances || {};
    settings.providerInstances.pi = Object.assign(settings.providerInstances.pi || {}, { driver: "pi", enabled: true });
    if (!isPi) {
        settings.providerInstances.pi.enabled = false;
    }
    settings.providerInstances.codex = Object.assign(settings.providerInstances.codex || {}, { driver: "codex", enabled: false });
    if (isCodex) {
        settings.providerInstances.codex.enabled = true;
    }
    settings.providerInstances.claudeAgent = Object.assign(settings.providerInstances.claudeAgent || {}, { driver: "claudeAgent", enabled: false });
    if (isClaude) {
        settings.providerInstances.claudeAgent.enabled = true;
    }

    const activeInstanceId = isClaude ? "claudeAgent" : (isCodex ? "codex" : "pi");
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
