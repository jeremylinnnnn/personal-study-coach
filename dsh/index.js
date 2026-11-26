import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'personal-study-coach'
export const inject = ['skills']

export function apply(ctx) {
  const path = fileURLToPath(new URL('../SKILL.md', import.meta.url))
  const resourceBase = {
    kind: 'directory',
    path: fileURLToPath(new URL('../', import.meta.url)),
  }
  const markdown = readFileSync(path, 'utf8')
  const [, frontmatter, body] = /^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]+)$/.exec(markdown) ?? []
  const description = frontmatter?.match(/^description: (.+)$/m)?.[1]
  if (!description || !body) throw new Error('Invalid personal-study-coach SKILL.md')

  const registration = join(homedir(), '.personal-study-coach', 'review-plan-location.txt')
  const content = [
    '## DSH 插件安装的总表登记',
    '',
    `本安装把总表路径登记在 \`${registration}\`。文件中保存一行总表的绝对路径。以后先读取它，首次登记时创建必要的目录。此文件就是下文及备考说明中的登记位置，升级插件后继续沿用。`,
    '',
    '若尚未登记，按下文查找已有总表。已确认其他本地安装的登记仍有效时，可复用它指向的总表并登记到这个文件。',
    '',
    body,
  ].join('\n')
  const definition = {
    name,
    description,
    content,
    path,
    resourceBase,
    source: 'bundled',
    provider: name,
    invocation: { modelInvocable: true, userInvocable: true },
  }

  ctx.skills.registerProvider(() => ({
    name,
    // Use the usual bundled rank so a user's local copy retains priority.
    async list() {
      const { content, ...summary } = definition
      return [{ ...summary, rank: 600, locator: path }]
    },
    async get() {
      return definition
    },
  }))
}
