"use client";

/**
 * Demo build only (next.config.ts aliases `@/components/kokonutui/ai-prompt` here): the
 * Ask prompt with the recorded questions above it, and a note when a typed question was
 * matched to a different recorded one.
 */
import { type ComponentProps, useEffect, useRef, useState } from "react";

import { DemoMatchNote, DemoSuggestions } from "../components/demo/demo-ask";
import AIPrompt from "../components/kokonutui/ai-prompt";
import { setLastMatch, subscribePicks } from "../lib/demo/ask-store";
import { cn } from "../lib/utils";

export default function AI_Prompt({ className, ...props }: ComponentProps<typeof AIPrompt>) {
  const onSubmitRef = useRef(props.onSubmit);
  const pendingRef = useRef<string | null>(null);
  const [picks, setPicks] = useState(0);

  useEffect(() => {
    onSubmitRef.current = props.onSubmit;
  });

  // A fresh Ask view has asked nothing yet.
  useEffect(() => setLastMatch(null), []);

  // A picked suggestion first sets the as-of date (the demo AsOfPicker hears the same
  // pick), then is sent once the Ask view has rendered with that date.
  useEffect(
    () =>
      subscribePicks((pick) => {
        pendingRef.current = pick.question;
        setPicks((n) => n + 1);
      }),
    [],
  );
  useEffect(() => {
    const question = pendingRef.current;
    if (question === null) return;
    pendingRef.current = null;
    onSubmitRef.current(question);
  }, [picks]);

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <DemoMatchNote />
      <DemoSuggestions disabled={props.responding === true || props.disabled === true} />
      <AIPrompt {...props} />
    </div>
  );
}
