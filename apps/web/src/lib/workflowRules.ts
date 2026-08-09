import type { WorkflowStep } from "@/lib/api";
import agentContracts from "@/lib/agent_io.generated.json";

export const WORKFLOW_AGENTS = Object.keys(agentContracts) as Array<
  keyof typeof agentContracts
>;

export type WorkflowAgent = (typeof WORKFLOW_AGENTS)[number];

export const AGENT_NAMES = Object.fromEntries(
  WORKFLOW_AGENTS.map((agent) => [agent, agentContracts[agent].name]),
) as Record<WorkflowAgent, string>;

export const AGENT_INPUTS = Object.fromEntries(
  WORKFLOW_AGENTS.map((agent) => [agent, [...agentContracts[agent].inputs]]),
) as Record<WorkflowAgent, string[]>;

export const AGENT_OUTPUTS = Object.fromEntries(
  WORKFLOW_AGENTS.map((agent) => [agent, [...agentContracts[agent].outputs]]),
) as Record<WorkflowAgent, string[]>;

export const ARTIFACT_NAMES: Record<string, string> = {
  course_idea_brief: "brief de la idea",
  research_brief: "research brief",
  course_plan: "plan del curso",
  lesson_content: "lecciones",
  slide_deck: "slides",
  teaching_script: "guion docente",
  voice_script: "guion de voz",
  audio: "audio narrado",
  video: "v\u00eddeo",
  subtitles: "subt\u00edtulos",
};

export interface ContextualArtifactAction {
  agent: WorkflowAgent;
  inputs: string[];
  outputs: string[];
  missing: string[];
  regenerates: boolean;
}

export function contextualArtifactActions(
  artifactType: string,
  selectedTypes: ReadonlySet<string>,
): ContextualArtifactAction[] {
  return WORKFLOW_AGENTS.filter(
    (agent) =>
      AGENT_INPUTS[agent].includes(artifactType) ||
      AGENT_OUTPUTS[agent].includes(artifactType),
  ).map((agent) => ({
    agent,
    inputs: AGENT_INPUTS[agent],
    outputs: AGENT_OUTPUTS[agent],
    missing: AGENT_INPUTS[agent].filter((type) => !selectedTypes.has(type)),
    regenerates: AGENT_OUTPUTS[agent].some((type) => selectedTypes.has(type)),
  }));
}

export function requiredInitialArtifacts(steps: WorkflowStep[]): string[] {
  if (steps.length === 0) return [];
  const firstAgent = steps[0].agent as WorkflowAgent;
  return (AGENT_INPUTS[firstAgent] ?? []).filter(
    (type) => type !== "course_idea_brief",
  );
}

export function availableArtifacts(steps: WorkflowStep[]): Set<string> {
  const available = new Set<string>(["course_idea_brief"]);
  for (const input of requiredInitialArtifacts(steps)) {
    available.add(input);
  }
  for (const step of steps) {
    const agent = step.agent as WorkflowAgent;
    for (const output of AGENT_OUTPUTS[agent] ?? []) {
      available.add(output);
    }
  }
  return available;
}

export function unavailableReason(
  agent: WorkflowAgent,
  steps: WorkflowStep[],
): string | null {
  if (steps.length === 0) return null;
  if (steps.some((step) => step.agent === agent)) {
    return "Este agente ya forma parte del workflow";
  }

  const available = availableArtifacts(steps);
  const missing = AGENT_INPUTS[agent].filter((input) => !available.has(input));
  if (missing.length === 0) return null;
  return `Necesita ${missing
    .map((type) => ARTIFACT_NAMES[type] ?? type)
    .join(" y ")}`;
}

export function validateWorkflowSteps(steps: WorkflowStep[]): string[] {
  if (steps.length === 0) return ["El workflow debe tener al menos un paso"];
  const problems: string[] = [];
  const built: WorkflowStep[] = [];
  for (const [index, step] of steps.entries()) {
    const agent = step.agent as WorkflowAgent;
    if (!WORKFLOW_AGENTS.includes(agent)) {
      problems.push(`Paso ${index + 1}: agente desconocido`);
      continue;
    }
    const reason = unavailableReason(agent, built);
    if (reason) problems.push(`Paso ${index + 1}: ${reason}`);
    built.push(step);
  }
  return problems;
}
