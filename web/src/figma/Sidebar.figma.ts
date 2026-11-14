// url=https://www.figma.com/design/I0dtgDaYeGWv360bEOOCK4/BoardNotes-Prototype?node-id=17-302
// source=web/src/components/Sidebar.tsx
// component=Sidebar
import figma from 'figma'
const instance = figma.selectedInstance

// Role decides which nav items show (lecturers also get Review queue and Upload lecture).
// Active is not a prop: the sidebar highlights the item matching the current route.
const role = instance.getEnum('Role', { Student: 'student', Lecturer: 'lecturer' })

export default {
  example:
    role === 'lecturer'
      ? figma.code`<Sidebar me={{ id: "u_lecturer", initials: "DR", name: "Dr. Rivera", role: "lecturer" }} reviewCount={reviewCount} />`
      : figma.code`<Sidebar me={{ id: "u_sam", initials: "SP", name: "Sam Patel", role: "student" }} />`,
  imports: ['import { Sidebar } from "@/components/Sidebar"'],
  id: 'sidebar',
  metadata: { nestable: false },
}
