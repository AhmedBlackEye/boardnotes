// url=https://www.figma.com/design/I0dtgDaYeGWv360bEOOCK4/BoardNotes-Prototype?node-id=20-250
// source=web/src/components/ChatMessage.tsx
// component=ChatMessage
import figma from 'figma'
const instance = figma.selectedInstance

const kind = instance.getEnum('Type', { Question: 'user', Answer: 'answer', 'Not covered': 'notice' })
const question = instance.getString('Question')
const answer = instance.getString('Answer')
const notCovered = instance.getString('Not covered')

const chip = kind === 'answer' ? instance.findInstance('Source chip') : null
let chipCode
if (chip && chip.type === 'INSTANCE') {
  chipCode = chip.executeTemplate().example
}

let example
if (kind === 'user') {
  example = figma.code`<ChatMessage kind="user">${question}</ChatMessage>`
} else if (kind === 'answer') {
  example = figma.code`<ChatMessage kind="answer" sources={<>${chipCode}</>}>${answer}</ChatMessage>`
} else {
  example = figma.code`<ChatMessage kind="notice">${notCovered}</ChatMessage>`
}

export default {
  example,
  imports: ['import { ChatMessage } from "@/components/ChatMessage"'],
  id: 'chat-message',
  metadata: { nestable: false },
}
