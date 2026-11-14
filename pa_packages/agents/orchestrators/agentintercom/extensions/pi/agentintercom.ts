// pa-container AgentIntercom extension for official Pi Coding Agent
import { execFileSync } from "node:child_process";

export default function agentIntercomExtension(pi: any) {
    const runCli = (args: string[]): string => {
        try {
            return execFileSync("agentintercom", args, {
                encoding: "utf-8",
                timeout: 5000,
            }).trim();
        } catch (err: any) {
            return err?.stdout?.toString() || err?.message || "agentintercom error";
        }
    };

    const drainUnread = (): string => {
        try {
            return execFileSync(
                "pa-intercom-hook",
                ["drain-text", "--harness", "pi", "--ack"],
                { encoding: "utf-8", timeout: 5000 }
            ).trim();
        } catch {
            return "";
        }
    };

    pi.on("session_start", async () => {
        try {
            execFileSync("pa-intercom-hook", ["register", "--harness", "pi"], {
                timeout: 3000,
            });
        } catch {
            // Ignore registration errors if bus is not yet initialized
        }
    });

    // Poll unread inbox after every turn; if a human or peer agent sent a message,
    // inject it as a followUp message so Pi processes it automatically.
    pi.on("turn_end", async () => {
        const incoming = drainUnread();
        if (incoming && typeof pi.sendMessage === "function") {
            pi.sendMessage(
                {
                    customType: "agentintercom-inbox",
                    content: incoming,
                    display: true,
                },
                { deliverAs: "followUp", triggerTurn: true }
            );
        }
    });

    pi.registerTool({
        name: "intercom_peers",
        label: "Intercom Peers",
        description: "List active human and agent peers registered on AgentIntercom",
        parameters: { type: "object", properties: {} },
        async execute() {
            return { content: [{ type: "text", text: runCli(["peers", "--json"]) }] };
        },
    });

    pi.registerTool({
        name: "intercom_send",
        label: "Intercom Send",
        description: "Send a message or task to another peer on AgentIntercom",
        parameters: {
            type: "object",
            properties: {
                to: { type: "string", description: "Target peer name" },
                message: { type: "string", description: "Message content" },
            },
            required: ["to", "message"],
        },
        async execute(_id: string, params: { to: string; message: string }) {
            const out = runCli(["send", "--to", params.to, "--message", params.message]);
            return { content: [{ type: "text", text: out || "Sent" }] };
        },
    });

    pi.registerTool({
        name: "intercom_inbox",
        label: "Intercom Inbox",
        description: "Check unread messages in the AgentIntercom inbox",
        parameters: { type: "object", properties: {} },
        async execute() {
            return { content: [{ type: "text", text: runCli(["inbox", "--unread", "--json"]) }] };
        },
    });

    pi.registerTool({
        name: "intercom_ack",
        label: "Intercom Ack",
        description: "Acknowledge a processed AgentIntercom message ID",
        parameters: {
            type: "object",
            properties: {
                message_id: { type: "string", description: "Message ID to acknowledge" },
            },
            required: ["message_id"],
        },
        async execute(_id: string, params: { message_id: string }) {
            return { content: [{ type: "text", text: runCli(["ack", params.message_id]) }] };
        },
    });
}
