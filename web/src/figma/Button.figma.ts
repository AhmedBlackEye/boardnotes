// url=https://www.figma.com/design/I0dtgDaYeGWv360bEOOCK4/BoardNotes-Prototype?node-id=16-22
// source=web/src/components/Button.tsx
// component=Button
import figma from 'figma'
const instance = figma.selectedInstance

const label = instance.getString('Label')
const variant = instance.getEnum('Style', {
  Primary: 'primary',
  Secondary: 'secondary',
  Ghost: 'ghost',
  Success: 'success',
  Danger: 'danger',
})
// The code Button has one size; the small one is the same button with tighter padding.
const small = instance.getEnum('Size', { Medium: false, Small: true })

export default {
  example: figma.code`<Button variant="${variant}"${small ? ' className="px-3 py-1.5"' : ''}>${label}</Button>`,
  imports: ['import { Button } from "@/components/Button"'],
  id: 'button',
  metadata: { nestable: true },
}
