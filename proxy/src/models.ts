// MonkeyCode 模型管理 — 获取和缓存可用模型

import { AuthManager } from "./auth.js"
import { mkHeaders } from "./browser-headers.js"
import type { MonkeyCodeModel, InterfaceType, OpenAIModel } from "./types.js"

const MONKEYCODE_BASE_URL = process.env.MONKEYCODE_BASE_URL || "https://monkeycode-ai.com"

export class ModelManager {
  private auth: AuthManager
  private models: MonkeyCodeModel[] = []
  private lastFetch: number = 0
  private cacheTTL: number = 5 * 60 * 1000 // 5 分钟缓存

  constructor(auth: AuthManager) {
    this.auth = auth
  }

  /** 从 MonkeyCode 获取可用模型列表 */
  async fetchModels(): Promise<MonkeyCodeModel[]> {
    if (this.models.length > 0 && Date.now() - this.lastFetch < this.cacheTTL) {
      return this.models
    }

    const url = `${MONKEYCODE_BASE_URL}/api/v1/users/models`

    const response = await fetch(url, {
      headers: mkHeaders({
        Cookie: `${this.auth.getSessionCookieName()}=${this.auth.getSessionCookieSync()}`,
      }),
    })
    if (!response.ok) {
      throw new Error(`Failed to fetch models (${response.status}): ${await response.text()}`)
    }

    const result = await response.json()
    // 响应格式: { code: 0, data: { models: [...] } } 或 { models: [...] }
    const data = result.data || result
    this.models = data.models || []
    this.lastFetch = Date.now()

    console.log(`[Models] Fetched ${this.models.length} models`)
    return this.models
  }

  /** 转换为 OpenAI /v1/models 格式 */
  async toOpenAIModels(): Promise<OpenAIModel[]> {
    const models = await this.fetchModels()
    return models.map((m) => ({
      id: this.toOpenAIModelId(m),
      object: "model" as const,
      created: Math.floor(Date.now() / 1000),
      owned_by: m.provider,
    }))
  }

  /** 生成 OpenAI 兼容的模型 ID */
  toOpenAIModelId(m: MonkeyCodeModel): string {
    // 格式: monkeycode/{provider}/{model}
    return `monkeycode/${m.provider}/${m.model}`
  }

  /** 根据 OpenAI 模型 ID 查找 MonkeyCode 模型 */
  async resolveModel(openaiModelId: string): Promise<MonkeyCodeModel | null> {
    const models = await this.fetchModels()

    // 精确匹配 monkeycode/provider/model 格式
    const exact = models.find((m) => this.toOpenAIModelId(m) === openaiModelId)
    if (exact) return exact

    // 匹配 provider/model 格式
    const byProviderModel = models.find(
      (m) => `${m.provider}/${m.model}` === openaiModelId
    )
    if (byProviderModel) return byProviderModel

    // 模糊匹配 model 名称
    const byModelName = models.find((m) => m.model === openaiModelId)
    if (byModelName) return byModelName

    // 匹配 display_name
    const byDisplayName = models.find((m) => m.display_name === openaiModelId)
    if (byDisplayName) return byDisplayName

    // 默认模型
    const defaultModel = models.find((m) => m.is_default)
    if (defaultModel) return defaultModel

    return models[0] || null
  }

  /** 获取模型的接口类型 */
  getInterfaceType(model: MonkeyCodeModel): InterfaceType {
    return model.interface_type
  }

  /** 清除缓存 */
  clearCache(): void {
    this.models = []
    this.lastFetch = 0
  }
}
