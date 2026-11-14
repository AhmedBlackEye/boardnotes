// url=https://www.figma.com/design/I0dtgDaYeGWv360bEOOCK4/BoardNotes-Prototype?node-id=16-44
// source=web/src/components/StatusPill.tsx
// component=StatusPill
import figma from 'figma'
const instance = figma.selectedInstance

const label = instance.getString('Label')
const showDot = instance.getBoolean('Show dot')
const status = instance.getEnum('Status', {
  Verified: 'verified',
  'AI agrees': 'verified',
  'In review': 'in_review',
  Uncertain: 'uncertain',
  Draft: 'draft',
  Processing: 'processing',
  Flagged: 'flagged',
})

export default {
  example: figma.code`<StatusPill status="${status}"${showDot ? '' : ' showDot={false}'}>${label}</StatusPill>`,
  imports: ['import { StatusPill } from "@/components/StatusPill"'],
  id: 'status-pill',
  metadata: { nestable: true },
}
