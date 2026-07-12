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
  curator: "🔍 Curador",
  planner: "📋 Plan del curso",
  lessons: "✍️ Lecciones",
  slides: "🖼 Slides",
  script: "🎙 Guion docente",
  voice: "🗣 Adaptación a voz",
  video: "🎬 Vídeo",
};

type StepNodeData = {
  label: string;
  approval: boolean;
  selected: boolean;
  status?: string;
};

function StepNode({ data }: NodeProps) {
  const d = data as StepNodeData;
  const border = d.selected
    ? "border-indigo-500"
    : d.status === "done"
      ? "border-emerald-700"
      : d.status === "running"
        ? "border-indigo-600"
        : d.status === "failed"
          ? "border-red-700"
          : "border-neutral-700";
  return (
    <div
      className={`rounded-xl border-2 ${border} bg-neutral-900 px-4 py-3 text-sm text-neutral-100 shadow`}
    >
      <Handle type="target" position={Position.Left} className="!bg-neutral-500" />
      <div className="font-medium">{d.label}</div>
      {d.approval && (
        <div className="mt-1 text-xs text-amber-400">✋ aprobación humana</div>
      )}
      {d.status && d.status !== "pending" && (
        <div className="mt-1 text-xs text-neutral-400">{d.status}</div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-neutral-500" />
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
      position: { x: i * 220, y: 40 },
      data: {
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
    }));
    return { nodes, edges };
  }, [steps, selectedIndex, statuses]);

  return (
    <div className="h-48 w-full rounded-xl border border-neutral-800 bg-neutral-950">
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
        zoomOnScroll={false}
        preventScrolling={false}
        colorMode="dark"
      >
        <Background gap={16} color="#333" />
      </ReactFlow>
    </div>
  );
}
