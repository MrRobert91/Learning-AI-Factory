import type { WorkflowStep } from "@/lib/api";

export const WORKFLOW_AGENTS = [
  "curator",
  "planner",
  "lessons",
  "slides",
  "script",
  "voice",
  "video",
  "publisher",
] as const;

export type WorkflowAgent = (typeof WORKFLOW_AGENTS)[number];

export const AGENT_NAMES: Record<WorkflowAgent, string> = {
  curator: "Curador",
  planner: "Plan del curso",
  lessons: "Lecciones",
  slides: "Slides",
  script: "Guion docente",
  voice: "Adaptaci\u00f3n a voz",
  video: "V\u00eddeo",
  publisher: "Publicaci\u00f3n",
};

export const AGENT_INPUTS: Record<WorkflowAgent, string[]> = {
  curator: [],
  planner: ["research_brief"],
  lessons: ["research_brief", "course_plan"],
  slides: ["course_plan", "lesson_content"],
  script: ["slide_deck"],
  voice: ["teaching_script"],
  video: ["slide_deck", "voice_script"],
  publisher: ["video"],
};

export const AGENT_OUTPUTS: Record<WorkflowAgent, string[]> = {
  curator: ["research_brief"],
  planner: ["course_plan"],
  lessons: ["lesson_content"],
  slides: ["slide_deck"],
  script: ["teaching_script"],
  voice: ["voice_script"],
  video: ["video", "subtitles"],
  publisher: ["publication_package", "thumbnail"],
};

export const ARTIFACT_NAMES: Record<string, string> = {
  course_idea_brief: "brief de la idea",
  research_brief: "research brief",
  course_plan: "plan del curso",
  lesson_content: "lecciones",
  slide_deck: "slides",
  teaching_script: "guion docente",
  voice_script: "guion de voz",
  video: "v\u00eddeo",
  subtitles: "subt\u00edtulos",
};

export function availableArtifacts(steps: WorkflowStep[]): Set<string> {
  const available = new Set<string>(["course_idea_brief"]);
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
  if (steps.length === 0 && agent !== "curator") {
    return "El workflow debe empezar por Curador";
  }
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
