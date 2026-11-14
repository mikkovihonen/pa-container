// pa-container AgentIntercom plugin for OpenCode
import { execFileSync } from "node:child_process";

export const AgentIntercomPlugin = async ({ client }) => {
    const drainUnread = () => {
        try {
            return execFileSync(
                "pa-intercom-hook",
                ["drain-text", "--harness", "opencode", "--ack"],
                { encoding: "utf-8", timeout: 5000 }
            ).trim();
        } catch {
            return "";
        }
    };

    return {
        event: async ({ event }) => {
            if (event.type === "session.created") {
                try {
                    execFileSync("pa-intercom-hook", ["register", "--harness", "opencode"], {
                        timeout: 3000,
                    });
                } catch {}
            }

            if (event.type === "session.idle") {
                const incoming = drainUnread();
                if (incoming && client?.session?.prompt && event.properties?.sessionID) {
                    await client.session.prompt({
                        path: { id: event.properties.sessionID },
                        body: {
                            parts: [{ type: "text", text: incoming }],
                        },
                    });
                }
            }
        },
    };
};

export default AgentIntercomPlugin;
