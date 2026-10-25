"use client";

/**
 * @author: @kokonutui
 * @description: AI Prompt Input
 * @version: 2.0.0
 * @date: 2026-10-15
 * @license: MIT
 * @website: https://kokonutui.com
 * @github: https://github.com/kokonut-labs/kokonutui
 *
 * Installed with `bunx shadcn add @kokonutui/ai-prompt` and edited in place for Driftline:
 * the model and effort menus, attachments, the slash-command menu and the promo header
 * are gone (the Ask view has no use for them), the toolbar takes the caller's controls,
 * and `responding` is controlled by the caller, which owns the request and its stream.
 * All Motion animation is removed; animation arrives in P5b.
 */

import { ArrowUp } from "lucide-react";
import { type ReactNode, useId, useRef, useState } from "react";
import { Textarea } from "@/components/ui/textarea";
import { useAutoResizeTextarea } from "@/hooks/use-auto-resize-textarea";
import { cn } from "@/lib/utils";

interface AIPromptProps {
  placeholder?: string;
  /** Accessible name of the text box. */
  label?: string;
  /** True while a reply is in progress: the send button becomes Stop. */
  responding?: boolean;
  /** Blocks sending (not typing), e.g. while a Retry-After wait runs. */
  disabled?: boolean;
  /** Sends the message. The box clears; ↑ in an empty box brings it back. */
  onSubmit: (value: string) => void;
  /** Called when the user presses Stop (or Esc) while a reply is in progress. */
  onStop?: () => void;
  /** Controls shown in the toolbar under the text box, left of the send button. */
  toolbar?: ReactNode;
  className?: string;
}

function SendButton({
  responding,
  canSend,
  onSend,
  onStop,
}: {
  responding: boolean;
  canSend: boolean;
  onSend: () => void;
  onStop: () => void;
}) {
  return (
    <button
      aria-label={responding ? "Stop response" : "Send message"}
      className={cn(
        "relative flex size-8 shrink-0 items-center justify-center rounded-full",
        "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        // Fills in once there is something to send, so the button says
        // "ready" before it is pressed. Stop keeps the same fill.
        responding || canSend
          ? "bg-black text-white hover:bg-black/80 dark:bg-white dark:text-black dark:hover:bg-white/85"
          : "bg-black/5 text-black/30 dark:bg-white/10 dark:text-white/30",
      )}
      disabled={!(responding || canSend)}
      onClick={responding ? onStop : onSend}
      type="button"
    >
      {responding ? (
        <span aria-hidden="true" className="size-2.5 rounded-[2px] bg-current" />
      ) : (
        <ArrowUp aria-hidden="true" className="size-4" strokeWidth={2.25} />
      )}
    </button>
  );
}

export default function AI_Prompt({
  placeholder = "Ask a question",
  label = "Question",
  responding = false,
  disabled = false,
  onSubmit,
  onStop,
  toolbar,
  className,
}: AIPromptProps) {
  const [value, setValue] = useState("");
  // The last message sent, for ↑ in an empty prompt (as in a terminal).
  const lastSentRef = useRef("");
  const { textareaRef, adjustHeight } = useAutoResizeTextarea({
    minHeight: 56,
    maxHeight: 280,
  });
  const textareaId = useId();

  const canSend = value.trim().length > 0 && !responding && !disabled;

  const submit = () => {
    if (!canSend) {
      return;
    }
    lastSentRef.current = value;
    setValue("");
    adjustHeight(true);
    onSubmit(value.trim());
  };

  const stop = () => {
    onStop?.();
    textareaRef.current?.focus();
  };

  // ↑ in an empty prompt brings the last message back to edit.
  const recallLast = () => {
    setValue(lastSentRef.current);
    // After React writes the value: grow to fit, caret at the end.
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      adjustHeight();
      el?.setSelectionRange(el.value.length, el.value.length);
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter during IME composition confirms the candidate; it must not submit.
    if (e.nativeEvent.isComposing) {
      return;
    }
    if (value === "" && e.key === "ArrowUp" && lastSentRef.current) {
      e.preventDefault();
      recallLast();
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    } else if (e.key === "Escape" && responding) {
      e.preventDefault();
      stop();
    }
  };

  return (
    <div className={cn("w-full py-4", className)}>
      <div className="rounded-[22px] bg-black/[0.04] p-1 dark:bg-white/[0.04]">
        <div
          className={cn(
            "relative flex flex-col rounded-[18px] bg-white ring-1 ring-black/[0.08] dark:bg-zinc-900 dark:ring-white/10",
            "shadow-[0_1px_2px_rgb(0_0_0/0.04),0_6px_20px_-10px_rgb(0_0_0/0.12)]",
            "has-[textarea:focus-visible]:ring-2 has-[textarea:focus-visible]:ring-ring",
          )}
        >
          <label className="sr-only" htmlFor={textareaId}>
            {label}
          </label>
          <Textarea
            className="min-h-[56px] w-full resize-none rounded-none border-none bg-transparent px-4 pt-3.5 pb-1 text-[15px] text-black leading-relaxed shadow-none placeholder:text-black/35 focus-visible:ring-0 focus-visible:ring-offset-0 dark:bg-transparent dark:text-white dark:placeholder:text-white/35"
            id={textareaId}
            onChange={(e) => {
              setValue(e.target.value);
              adjustHeight();
            }}
            onKeyDown={handleKeyDown}
            placeholder={responding ? "Answering… Esc to stop" : placeholder}
            ref={textareaRef}
            value={value}
          />

          <div className="flex flex-wrap items-center gap-1 px-2.5 pt-1 pb-2.5">
            {toolbar}
            <div className="flex-1" />
            <SendButton canSend={canSend} onSend={submit} onStop={stop} responding={responding} />
          </div>
        </div>
      </div>
    </div>
  );
}
