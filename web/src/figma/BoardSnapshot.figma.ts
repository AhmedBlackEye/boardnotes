// url=https://www.figma.com/design/I0dtgDaYeGWv360bEOOCK4/BoardNotes-Prototype?node-id=20-114
// source=web/src/components/BoardSnapshot.tsx
// component=BoardSnapshot
import figma from 'figma'
const instance = figma.selectedInstance

const text = instance.getString('Board text')
const caption = instance.getString('Caption')
const size = instance.getEnum('Size', { Large: 'large', Compact: 'small' })

export default {
  example: figma.code`<BoardSnapshot caption="${caption}" text="${text}" imageUrl={snapshotUrl} size="${size}" />`,
  imports: ['import { BoardSnapshot } from "@/components/BoardSnapshot"'],
  id: 'board-snapshot',
  metadata: { nestable: true },
}
