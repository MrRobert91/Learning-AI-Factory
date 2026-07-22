"use client";

import { useMemo } from "react";
import {
  Background,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { WorkflowStep } from "@/lib/api";

const AGENT_LABELS: Record<string, string> = {
  curator: "Curador",
  planner: "Plan del curso",
  lessons: "Lecciones",
  slides: "Slides",
  script: "Guion docente",
  voice: "Adaptación a voz",
  video: "Vídeo",
  publisher: "Publicación",
};

type StepNodeData = {
  index: number;
  label: string;
  approval: boolean;
  selected: boolean;
  status?: string;
};

function StepNode({ data }: NodeProps) {
  const d = data as StepNodeData;
  const border = d.selected
    ? "border-indigo-400 shadow-[0_0_0_3px_rgba(129,140,248,0.2)]"
    : d.status === "done"
      ? "border-emerald-500/60"
      : d.status === "running"
        ? "border-indigo-500/70"
        : d.status === "failed"
          ? "border-red-500/60"
          : "border-zinc-300";
  return (
    <div
      className={`min-w-48 rounded-md border-2 ${border} bg-[#fbf6ea] px-4 py-3 text-sm text-[#241d18] shadow-[3px_3px_0_rgba(36,29,24,0.85)] transition-shadow`}
    >
      <Handle type="target" position={Position.Left} className="!bg-zinc-500" />
      <div className="flex items-center gap-2">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#ece2d0] text-[10px] font-semibold text-zinc-700">
          {d.index + 1}
        </span>
        <span className="font-medium">{d.label}</span>
      </div>
      {d.approval && (
        <div className="mt-1 text-[11px] font-medium text-amber-700">
          Aprobación humana
        </div>
      )}
      {d.status && d.status !== "pending" && (
        <div className="mt-1 text-[11px] text-zinc-600">{d.status}</div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-zinc-500" />
    </div>
  );
}

const nodeTypes = { step: StepNode };

interface Props {
  steps: WorkflowStep[];
  selectedIndex?: number | null;
  statuses?: Record<number, string>;
  onSelect?: (index: number) => void;
}

export default function WorkflowCanvas({
  steps,
  selectedIndex,
  statuses,
  onSelect,
}: Props) {
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = steps.map((step, i) => ({
      id: String(i),
      type: "step",
      position: { x: i * 230, y: 40 },
      data: {
        index: i,
        label: AGENT_LABELS[step.agent] ?? step.agent,
        approval: Boolean(step.approval_after),
        selected: selectedIndex === i,
        status: statuses?.[i],
      },
      draggable: false,
    }));
    const edges: Edge[] = steps.slice(1).map((_s, i) => ({
      id: `e${i}`,
      source: String(i),
      target: String(i + 1),
      animated: statuses?.[i + 1] === "running",
      style: { stroke: "rgba(36,29,24,0.38)", strokeWidth: 2 },
    }));
    return { nodes, edges };
  }, [steps, selectedIndex, statuses]);

  return (
    <div className="card h-[min(68vh,720px)] min-h-[480px] w-full overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_e, node) => onSelect?.(Number(node.id))}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesConnectable={false}
        elementsSelectable={Boolean(onSelect)}
        panOnDrag
        zoomOnScroll
        preventScrolling={false}
        colorMode="light"
        style={{ background: "transparent" }}
      >
        <Background gap={22} color="rgba(36,29,24,0.12)" />
      </ReactFlow>
    </div>
  );
}
