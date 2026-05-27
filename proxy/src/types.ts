// MonkeyCode API 协议类型定义

// ========== 认证 ==========

export interface TeamLoginRequest {
  username: string
  password: string // MD5 哈希
}

export interface TeamLoginResponse {
  user: MonkeyCodeUser
  team: MonkeyCodeTeam
}

export interface MonkeyCodeUser {
  id: string
  name: string
  email: string
  avatar: string
  is_admin: boolean
  subscription_level: string
}

export interface MonkeyCodeTeam {
  id: string
  name: string
  slug: string
}

// ========== 模型 ==========

export type ModelProvider =
  | "siliconflow"
  | "openai"
  | "ollama"
  | "deepseek"
  | "moonshot"
  | "azure_openai"
  | "baizhicloud"
  | "hunyuan"
  | "bailian"
  | "volcengine"
  | "gemini"
  | "other"

export type InterfaceType = "openai_chat" | "openai_responses" | "anthropic"

export type AccessLevel = "basic" | "pro" | "ultra"

export type OwnerType = "private" | "team" | "public"

export interface MonkeyCodeModel {
  id: string  // UUID string from backend
  provider: ModelProvider
  api_key: string
  base_url: string
  model: string
  temperature: number
  is_default: boolean
  interface_type: InterfaceType
  is_free: boolean
  access_level: AccessLevel
  thinking_enabled: boolean
  context_limit: number
  output_limit: number
  owner: OwnerType
  name: string
  display_name: string
  description: string
}

// ========== WebSocket 消息 ==========

export interface TaskStreamMessage {
  type: string
  data: string
  kind?: string
  timestamp?: number
}

export interface UserInputMessage {
  type: "user-input"
  data: string // 纯文本或 JSON.stringify({content: base64, attachments: []})
}

export interface UserCancelMessage {
  type: "user-cancel"
  data: string
}

// ========== ACP 事件 ==========

export interface ACPSessionUpdate {
  type: string
  text?: string
  content?: string
  input_tokens?: number
  output_tokens?: number
  total_tokens?: number
  [key: string]: unknown
}

// ========== OpenAI 兼容类型 ==========

export interface OpenAIChatCompletionRequest {
  model: string
  messages: OpenAIMessage[]
  temperature?: number
  max_tokens?: number
  stream?: boolean
}

export interface OpenAIMessage {
  role: "system" | "user" | "assistant"
  content: string
}

export interface OpenAIChatCompletionResponse {
  id: string
  object: "chat.completion"
  created: number
  model: string
  choices: {
    index: number
    message: { role: string; content: string }
    finish_reason: string
  }[]
  usage: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  }
}

export interface OpenAIChatCompletionChunk {
  id: string
  object: "chat.completion.chunk"
  created: number
  model: string
  choices: {
    index: number
    delta: { role?: string; content?: string }
    finish_reason: string | null
  }[]
  usage?: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  }
}

export interface OpenAIModel {
  id: string
  object: "model"
  created: number
  owned_by: string
}

export interface OpenAIModelsResponse {
  object: "list"
  data: OpenAIModel[]
}
