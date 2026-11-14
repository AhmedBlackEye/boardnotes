// url=https://www.figma.com/design/I0dtgDaYeGWv360bEOOCK4/BoardNotes-Prototype?node-id=16-51
// source=web/src/components/SourceChip.tsx
// component=SourceChip
import figma from 'figma'
const instance = figma.selectedInstance

const label = instance.getString('Label')
const type = instance.getEnum('Type', { Timestamp: 'timestamp', Reference: 'reference' })

// Timestamps take seconds (float) and format mm:ss themselves; references take a label.
export default {
  example:
    type === 'timestamp'
      ? figma.code`<SourceChip seconds={seconds} onClick={() => seek(seconds)} /> {/* shows ${label} */}`
      : figma.code`<SourceChip type="reference" label="${label}" />`,
  imports: ['import { SourceChip } from "@/components/SourceChip"'],
  id: 'source-chip',
  metadata: { nestable: true },
}
