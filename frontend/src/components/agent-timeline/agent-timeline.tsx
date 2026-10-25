"use client";

/**
 * The live agent timeline: the answer graph's nodes light up from `step` events, the
 * subagent branches expand in parallel, claims flip ✓/✗ and the re-retrieve loop shows
 * as an iteration count. Motion owns every animation here (spec section 9); with reduced
 * motion nothing animates and every element renders in its final state.
 */
import { CircleCheck, CircleDashed, CircleX } from "lucide-react";
import { AnimatePresence, LayoutGroup, MotionConfig, motion, useReducedMotion } from "motion/react";
import { useId, useState } from "react";

import { formatDate, formatValidity, stepLabel } from "@/lib/ask/format";
import { cn } from "@/lib/utils";

import {
  GRAPH_NODES,
  summarizeTimeline,
  type BranchState,
  type ClaimCheck,
  type NodeName,
  type NodeState,
  type NodeStatus,
  type TimelineState,
} from "./reducer";

export interface AgentTimelineProps {
  state: TimelineState;
  /**
   * Like Motion's `MotionConfig reducedMotion`: `"user"` (the default) follows the
   * device's `prefers-reduced-motion`, `"always"` never animates, `"never"` always does.
   */
  reducedMotion?: "user" | "always" | "never";
  className?: string;
}

/** Nodes only drawn once the run reaches them: the loop and the human-review pause. */
const CONDITIONAL = new Set<NodeName>(["re_retrieve", "review"]);

const STATUS_TEXT: Record<NodeStatus, string> = {
  pending: "not reached",
  active: "running",
  done: "done",
  skipped: "skipped",
  failed: "failed",
  waiting: "waiting",
};

const DOT: Record<NodeStatus, string> = {
  pending: "border-border bg-background",
  active: "border-sky-500 bg-sky-500",
  done: "border-emerald-600 bg-emerald-600",
  skipped: "border-border bg-muted",
  failed: "border-destructive bg-destructive",
  waiting: "border-amber-500 bg-amber-500",
};

const words = (value: string) => value.replaceAll("_", " ");

function seconds(ms: number | null): string | null {
  if (ms === null) return null;
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function nodeStatusText(node: NodeState, state: TimelineState): string {
  if (node.name === "cache" && state.cache && node.status !== "pending") return state.cache;
  if (node.status === "active" && node.retrying) return "retrying";
  return STATUS_TEXT[node.status];
}

/** What a node's details panel says, from its last `step` event's `detail`. */
function describeNode(node: NodeState, state: TimelineState): string[] {
  const d = node.detail;
  const n = (key: string) => (typeof d[key] === "number" ? (d[key] as number) : null);
  const s = (key: string) => (typeof d[key] === "string" ? (d[key] as string) : null);
  const lines: string[] = [];
  switch (node.name) {
    case "classify": {
      const asOf = s("as_of");
      if (asOf)
        lines.push(`As of ${formatDate(asOf)} (from the ${words(s("source") ?? "request")})`);
      if (s("refused")) lines.push(`Refused: ${words(s("refused")!)}`);
      if (d.empty_corpus === true) lines.push("No documents are in force yet");
      break;
    }
    case "cache":
      if (state.cache === "hit") {
        lines.push(
          `Cache hit${n("similarity") !== null ? ` (similarity ${n("similarity")!.toFixed(2)})` : ""}`,
        );
      } else if (state.cache === "miss") lines.push("No cached answer for this question and date");
      else if (state.cache === "skipped") lines.push("The answer cache is off");
      break;
    case "plan": {
      const subs = Array.isArray(d.sub_questions) ? d.sub_questions.length : null;
      if (s("mode"))
        lines.push(
          `${s("mode")} plan${subs !== null ? `, ${subs} sub-question${subs === 1 ? "" : "s"}` : ""}`,
        );
      if (s("error")) lines.push("The plan was malformed, so the question is asked as is");
      break;
    }
    case "subagent":
      if (state.branches.length) lines.push(`${state.branches.length} searches in parallel`);
      break;
    case "merge":
      if (n("evidence") !== null) lines.push(`${n("evidence")} evidence passages merged`);
      break;
    case "draft":
      if (n("attempt") !== null) lines.push(`Attempt ${n("attempt")! + 1}`);
      if (n("claims") !== null) lines.push(`${n("claims")} claims drafted`);
      if (s("reason") === "repair") lines.push("Repairing a malformed draft");
      if (s("error")) lines.push(`Error: ${words(s("error")!)}`);
      break;
    case "verify":
      if (n("supported") !== null) {
        lines.push(`${n("supported")} supported, ${n("unsupported") ?? 0} unsupported`);
      }
      break;
    case "re_retrieve":
      if (n("attempt") !== null) lines.push(`Re-retrieve pass ${n("attempt")}`);
      if (n("claims") !== null) lines.push(`For ${n("claims")} unsupported claims`);
      if (n("found") !== null) lines.push(`${n("found")} new passages found`);
      break;
    case "respond":
      if (s("outcome")) lines.push(`Outcome: ${words(s("outcome")!)}`);
      if (s("error")) lines.push(`Error: ${words(s("error")!)}`);
      break;
    case "review":
      if (s("reason")) lines.push(`Reason: ${words(s("reason")!)}`);
      if (s("action")) lines.push(`Reviewer: ${s("action")}`);
      break;
  }
  const at = seconds(node.tMs);
  if (at) lines.push(`At ${at}`);
  return lines.length ? lines : ["No details yet"];
}

export function AgentTimeline({ state, reducedMotion = "user", className }: AgentTimelineProps) {
  const prefersReduced = useReducedMotion();
  const reduce =
    reducedMotion === "always" || (reducedMotion === "user" && prefersReduced === true);
  const [expanded, setExpanded] = useState(true);
  const [open, setOpen] = useState<NodeName[]>([]);
  const listId = useId();

  const toggleNode = (name: NodeName) =>
    setOpen((current) =>
      current.includes(name) ? current.filter((n) => n !== name) : [...current, name],
    );

  const visible = GRAPH_NODES.filter((name) => !CONDITIONAL.has(name) || state.lit.includes(name));
  const answer = state.answer;

  return (
    <MotionConfig
      reducedMotion={reduce ? "always" : "never"}
      transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 420, damping: 34 }}
    >
      <section
        aria-label="Agent timeline"
        className={cn(
          "rounded-2xl border border-border bg-card px-4 py-3 text-card-foreground",
          className,
        )}
      >
        <header className="flex flex-wrap items-center gap-2">
          <h2 className="font-heading text-sm font-semibold">Agent timeline</h2>
          {state.iteration > 0 ? (
            <span className="rounded-full bg-sky-500/10 px-2 py-0.5 text-[11px] font-medium text-sky-700 dark:text-sky-300">
              Pass {state.iteration + 1}
            </span>
          ) : null}
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={listId}
            onClick={() => setExpanded((v) => !v)}
            className="ml-auto rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {expanded ? "Hide steps" : "Show steps"}
          </button>
        </header>

        <p aria-live="polite" aria-atomic="true" className="mt-1 text-xs text-muted-foreground">
          {summarizeTimeline(state)}
        </p>

        {expanded ? (
          <LayoutGroup>
            <motion.ol
              id={listId}
              aria-label="Agent steps"
              layout={!reduce}
              className="mt-3 flex flex-col"
            >
              <AnimatePresence initial={false}>
                {visible.map((name) => (
                  <NodeRow
                    key={name}
                    node={state.nodes[name]}
                    state={state}
                    reduce={reduce}
                    open={open.includes(name)}
                    onToggle={() => toggleNode(name)}
                  />
                ))}
              </AnimatePresence>
            </motion.ol>
          </LayoutGroup>
        ) : null}

        {state.phase === "failed" && state.error ? (
          <p className="mt-3 rounded-lg border border-destructive/40 px-3 py-2 text-xs">
            The agent stopped: {state.error.code}
            {state.error.message ? ` (${state.error.message})` : ""}.
          </p>
        ) : null}

        {answer && answer.status !== "answered" ? (
          <div className="mt-3 rounded-lg border border-amber-500/40 px-3 py-2">
            <h3 className="text-sm font-semibold">
              {answer.status === "refused"
                ? "Refused: declined to answer"
                : "Refused: not enough evidence"}
            </h3>
            <p className="mb-2 text-xs text-muted-foreground">
              No claim could be verified against sources in force on {formatDate(answer.as_of)}, so
              Driftline refuses rather than guesses.
            </p>
            {answer.nearest_sources?.length ? (
              <ul aria-label="Sources the agent considered" className="flex flex-col gap-1 text-xs">
                {answer.nearest_sources.map((source) => (
                  <li key={source.version_id}>
                    <span className="font-medium">{source.title}</span>{" "}
                    <span className="text-muted-foreground">
                      v{source.version_no} · {formatValidity(source.valid_from, source.valid_to)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground">No nearby sources were found.</p>
            )}
          </div>
        ) : null}
      </section>
    </MotionConfig>
  );
}

function NodeRow({
  node,
  state,
  reduce,
  open,
  onToggle,
}: {
  node: NodeState;
  state: TimelineState;
  reduce: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  const detailsId = useId();
  const order = state.lit.indexOf(node.name);
  const label = stepLabel(node.name);
  const statusText = nodeStatusText(node, state);
  const showRuns =
    node.name === "re_retrieve" ? node.runs > 0 : node.name !== "subagent" && node.runs > 1;

  return (
    <motion.li
      layout={!reduce}
      initial={reduce ? false : { opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      data-node={node.name}
      data-status={node.status}
      data-lit-order={order >= 0 ? order : undefined}
      className="relative pb-2 pl-6 last:pb-0"
    >
      {/* The rail between nodes. */}
      <span aria-hidden="true" className="absolute top-4 bottom-0 left-[7px] w-px bg-border" />
      <motion.span
        aria-hidden="true"
        initial={false}
        // The pulse is decoration: the colour and the status text carry the state.
        animate={
          reduce
            ? undefined
            : { scale: node.status === "active" || node.status === "waiting" ? 1.3 : 1 }
        }
        className={cn("absolute top-1.5 left-0.5 size-3 rounded-full border-2", DOT[node.status])}
      />
      <button
        type="button"
        aria-label={`${label}: ${statusText}${showRuns ? `, run ${node.runs} times` : ""}`}
        aria-expanded={open}
        aria-controls={detailsId}
        onClick={onToggle}
        className={cn(
          "flex w-full items-center gap-2 rounded-md px-1 py-0.5 text-left text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          node.status === "pending" || node.status === "skipped" ? "text-muted-foreground" : "",
        )}
      >
        <span className="font-medium">{label}</span>
        <span className="text-xs text-muted-foreground">{statusText}</span>
        {showRuns ? (
          <span className="rounded bg-muted px-1 text-[11px] tabular-nums">×{node.runs}</span>
        ) : null}
        {node.tMs !== null ? (
          <span className="ml-auto text-[11px] tabular-nums text-muted-foreground">
            {seconds(node.tMs)}
          </span>
        ) : null}
      </button>

      {open ? (
        <ul id={detailsId} className="mt-1 ml-1 text-xs text-muted-foreground">
          {describeNode(node, state).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}

      {node.name === "subagent" && state.branches.length ? (
        <Branches branches={state.branches} reduce={reduce} />
      ) : null}
      {node.name === "verify" && state.claims.length ? (
        <ClaimChecks claims={state.claims} reduce={reduce} />
      ) : null}
    </motion.li>
  );
}

function Branches({ branches, reduce }: { branches: BranchState[]; reduce: boolean }) {
  return (
    <motion.ul
      layout={!reduce}
      aria-label="Parallel searches"
      className="mt-1.5 grid gap-1.5 sm:grid-cols-[repeat(auto-fit,minmax(10rem,1fr))]"
    >
      <AnimatePresence initial={false}>
        {branches.map((branch) => (
          <motion.li
            key={branch.branch}
            layout={!reduce}
            initial={reduce ? false : { opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={reduce ? { duration: 0 } : { delay: branch.branch * 0.05 }}
            data-status={branch.status}
            className={cn(
              "rounded-lg border px-2 py-1.5 text-xs",
              branch.status === "active" ? "border-sky-500/60" : "border-border",
              branch.status === "failed" ? "border-destructive/60" : "",
            )}
          >
            {/* A single branch searches the question as asked: no need to repeat it. */}
            <span className="block leading-snug">
              {branches.length > 1 && branch.question
                ? branch.question
                : branches.length > 1
                  ? `Search ${branch.branch + 1}`
                  : "The question as asked"}
            </span>
            <span className="text-muted-foreground">
              {branch.status === "done" && branch.kept !== null && branch.retrieved !== null
                ? `${branch.kept} of ${branch.retrieved} kept${branch.reranked === false ? " (not reranked)" : ""}`
                : STATUS_TEXT[branch.status]}
            </span>
          </motion.li>
        ))}
      </AnimatePresence>
    </motion.ul>
  );
}

function ClaimChecks({ claims, reduce }: { claims: ClaimCheck[]; reduce: boolean }) {
  return (
    <ul aria-label="Claim checks" className="mt-1.5 flex flex-col gap-1">
      {claims.map((claim) => {
        const n = claim.idx + 1;
        const Icon =
          claim.verified === null ? CircleDashed : claim.verified ? CircleCheck : CircleX;
        const name =
          claim.verified === null
            ? `Claim ${n} being checked`
            : claim.verified
              ? `Claim ${n} verified`
              : `Claim ${n} not verified`;
        return (
          <li key={claim.idx} className="flex items-start gap-1.5 text-xs">
            {/* Keyed on the verdict: a new verdict remounts the icon, which flips in. */}
            <motion.span
              key={String(claim.verified)}
              initial={reduce ? false : { rotateY: 90, opacity: 0 }}
              animate={{ rotateY: 0, opacity: 1 }}
              className="inline-flex"
            >
              <Icon
                role="img"
                aria-label={name}
                className={cn(
                  "size-4 shrink-0",
                  claim.verified === null
                    ? "text-muted-foreground"
                    : claim.verified
                      ? "text-emerald-600"
                      : "text-destructive",
                )}
              />
            </motion.span>
            <span>
              Claim {n}
              {claim.verified === false && claim.reason ? (
                <span className="text-muted-foreground"> · {words(claim.reason)}</span>
              ) : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
