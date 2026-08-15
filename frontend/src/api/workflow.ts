import { api } from './client'

export interface WorkflowTemplate {
  id: string
  workflow_id: string
  name: string
  description: string
  source: 'fixed' | 'custom'
  editable: boolean
  start: string
  nodes: Record<string, any>
  output: string | null
}

export interface GenerateWorkflowResult {
  workflow_json: Record<string, any>
  description: string
}

export interface WorkflowRunResult {
  run_id: string
  workflow_id: string
  status: string
  logs: any[]
  results: Record<string, any>
  final_output: any
  error: string | null
  pending_confirm_nodes?: string[]
}

export interface ToolInfo {
  name: string
  description: string
  parameters: Record<string, any>
}

export interface DimensionInfo {
  key: string
  label: string
}

export const workflowApi = {
  templates: async (): Promise<WorkflowTemplate[]> => {
    const { data } = await api.get<WorkflowTemplate[]>('/workflow/templates')
    return data
  },

  tools: async (): Promise<ToolInfo[]> => {
    const { data } = await api.get<{ tools: ToolInfo[] }>('/agent/tools')
    return data.tools
  },

  dimensions: async (): Promise<DimensionInfo[]> => {
    const { data } = await api.get<{ dimensions: DimensionInfo[] }>('/agent/dimensions')
    return data.dimensions
  },

  generate: async (userPrompt: string): Promise<GenerateWorkflowResult> => {
    const { data } = await api.post<GenerateWorkflowResult>('/agent/generate-workflow', {
      user_prompt: userPrompt,
    })
    return data
  },

  run: async (
    workflowJson: Record<string, any>,
    userVars: Record<string, any> = {},
  ): Promise<WorkflowRunResult> => {
    const { data } = await api.post<WorkflowRunResult>('/workflow/run', {
      workflow_json: workflowJson,
      user_vars: userVars,
    })
    return data
  },

  resume: async (runId: string): Promise<WorkflowRunResult> => {
    const { data } = await api.post<WorkflowRunResult>(`/workflow/resume/${runId}`)
    return data
  },

  saveTemplate: async (payload: {
    name: string
    description?: string
    workflow_json: Record<string, any>
  }): Promise<WorkflowTemplate> => {
    const { data } = await api.post<WorkflowTemplate>('/workflow/templates', payload)
    return data
  },

  deleteTemplate: async (templateId: string): Promise<void> => {
    await api.delete(`/workflow/templates/${templateId}`)
  },

  getRun: async (runId: string): Promise<any> => {
    const { data } = await api.get(`/workflow/${runId}`)
    return data
  },
}