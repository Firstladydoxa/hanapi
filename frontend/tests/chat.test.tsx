import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Chat } from "@/components/Chat";
import { api, type ConversationDetail, type ProjectDetail } from "@/lib/api";

const project = { id: "p1", name: "Pilot", domain: null, style: null, member_role: "translator", instructions: null, can_approve: true, language_directions: [] } as ProjectDetail;
const detail = (over: Partial<ConversationDetail> = {}): ConversationDetail => ({
  id: "c1", project_id: "p1", project_name: "Pilot", title: "New conversation", status: "active", created_at: "", updated_at: "", last_message_at: null, message_count: 1, preview: null,
  has_more_before: false, starters: ["Help me translate a text."],
  messages: [{ id: "m1", seq: 1, role: "assistant", content: "Hello, Alice! Welcome to HAN.", kind: "greeting", created_at: new Date().toISOString(), translation: null, clarification: null, actions: [], sources: [] }], ...over,
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Chat", () => {
  it("opens a new conversation with the stored greeting and starters, and sends to that conversation", async () => {
    vi.spyOn(api.conversations, "list").mockResolvedValue([]);
    const create = vi.spyOn(api.conversations, "create").mockResolvedValue(detail());
    const send = vi.spyOn(api.conversations, "send").mockResolvedValue({ conversation_id: "c1", reply: "Sure.", translation: null, clarification: null, actions: [], sources: [{ title: "Using HAN", category: "platform", version: 1 }] });
    render(<Chat project={project} onOpenWorkspace={vi.fn()} />);
    expect(await screen.findByText(/Hello, Alice/)).toBeTruthy();
    expect(create).toHaveBeenCalledWith("p1");
    fireEvent.click(screen.getByRole("button", { name: "Help me translate a text." }));
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(send).toHaveBeenCalledWith("c1", { message: "Help me translate a text.", context_translation_id: undefined }));
    expect(await screen.findByText(/Based on: Using HAN/)).toBeTruthy();
  });

  it("continues the latest conversation instead of greeting again", async () => {
    vi.spyOn(api.conversations, "list").mockResolvedValue([{ id: "c9", project_id: "p1", project_name: "Pilot", title: "Earlier", status: "active", created_at: "", updated_at: "", last_message_at: null, message_count: 4, preview: "x" }]);
    const create = vi.spyOn(api.conversations, "create");
    const get = vi.spyOn(api.conversations, "get").mockResolvedValue(detail({ id: "c9", title: "Earlier" }));
    render(<Chat project={project} onOpenWorkspace={vi.fn()} />);
    await waitFor(() => expect(get).toHaveBeenCalledWith("c9"));
    expect(create).not.toHaveBeenCalled();
  });
});
