// url=https://www.figma.com/design/I0dtgDaYeGWv360bEOOCK4/BoardNotes-Prototype?node-id=20-166
// source=web/src/components/NoteBullet.tsx
// component=NoteBullet
import figma from 'figma'
const instance = figma.selectedInstance

const text = instance.getString('Text')
const formula = instance.getString('Formula')
const showFormula = instance.getBoolean('Show formula')
const showBoardRef = instance.getBoolean('Show board ref')
const showStatus = instance.getBoolean('Show status')
const state = instance.getEnum('State', { Default: 'default', Selected: 'selected', Uncertain: 'uncertain' })

// Source chips and the status pill are children; each renders through its own template.
const timestamp = instance.findInstance('Timestamp')
let timestampCode
if (timestamp && timestamp.type === 'INSTANCE') {
  timestampCode = timestamp.executeTemplate().example
}
const boardRef = showBoardRef ? instance.findInstance('Board ref') : null
let boardRefCode
if (boardRef && boardRef.type === 'INSTANCE') {
  boardRefCode = boardRef.executeTemplate().example
}
const status = showStatus ? instance.findInstance('Status') : null
let statusCode
if (status && status.type === 'INSTANCE') {
  statusCode = status.executeTemplate().example
}

export default {
  example: figma.code`<NoteBullet text="${text}"${showFormula ? figma.code` latex="${formula}"` : ''} state="${state}" onSelect={select}>
  ${timestampCode}
  ${boardRefCode}
  ${statusCode}
</NoteBullet>`,
  imports: ['import { NoteBullet } from "@/components/NoteBullet"'],
  id: 'note-bullet',
  metadata: { nestable: false },
}
