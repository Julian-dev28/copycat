/**
 * The native <dialog> fires `close` after a programmatic el.close() too, a tick
 * later. Reporting that as a user close ran the parent's cancel handler after it
 * had moved on: the Trade ticket's "Tighter liquidation" confirm opened "Copy with
 * real money?", then the stale close wiped the confirm chain and shut it again,
 * so "Copy at this leverage anyway" did nothing (2026-10-15). jsdom has no
 * showModal/close: the polyfill below mirrors the spec's async close event.
 */
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Dialog } from "./Dialog";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

beforeAll(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const proto = HTMLDialogElement.prototype as HTMLDialogElement & { showModal?: () => void; close?: () => void };
  if (typeof proto.showModal !== "function") {
    proto.showModal = function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    };
    proto.close = function (this: HTMLDialogElement) {
      if (!this.hasAttribute("open")) return;
      this.removeAttribute("open");
      setTimeout(() => this.dispatchEvent(new Event("close")), 0);   // the spec queues the close event
    };
  }
});

const tick = () => act(() => new Promise<void>((r) => setTimeout(r, 5)));

let root: Root | null = null;
let host: HTMLElement | null = null;
function mount(ui: React.ReactElement) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root!.render(ui));
}
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = null;
  host = null;
});

describe("Dialog and the native close event", () => {
  it("does not report a programmatic close (open -> false) as a user close", async () => {
    const onClose = vi.fn();
    mount(<Dialog open onClose={onClose} title="A" />);
    expect(document.querySelector("dialog")!.hasAttribute("open")).toBe(true);
    act(() => root!.render(<Dialog open={false} onClose={onClose} title="A" />));
    await tick();
    expect(document.querySelector("dialog")!.hasAttribute("open")).toBe(false);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("reports Esc (cancel) and a close the user made while it was open", async () => {
    const onClose = vi.fn();
    mount(<Dialog open onClose={onClose} title="A" />);
    const el = document.querySelector("dialog")!;
    act(() => {
      el.dispatchEvent(new Event("cancel", { bubbles: true }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
    act(() => {
      el.dispatchEvent(new Event("close", { bubbles: true }));   // e.g. a form method="dialog" submit
    });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("a confirm that opens the next dialog is not cancelled by the first one closing", async () => {
    const log: string[] = [];
    function Chain() {
      const [step, setStep] = useState<"a" | "b" | null>("a");
      return (
        <>
          <Dialog open={step === "a"} onClose={() => { log.push("A cancel"); setStep(null); }} title="A"
            footer={<button type="button" onClick={() => setStep("b")}>Next</button>} />
          <Dialog open={step === "b"} onClose={() => { log.push("B cancel"); setStep(null); }} title="B" />
        </>
      );
    }
    mount(<Chain />);
    act(() => {
      (document.querySelector("button") as HTMLButtonElement).click();
    });
    await tick();
    const [a, b] = Array.from(document.querySelectorAll("dialog"));
    expect(a.hasAttribute("open")).toBe(false);
    expect(b.hasAttribute("open"), "the second dialog stays open after the first one's close event").toBe(true);
    expect(log).toEqual([]);
  });
});
